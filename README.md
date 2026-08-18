# Image Optimizer

Django REST Framework service that compresses uploaded images down to a
per-image-type target file size, while preserving as much visual quality as
possible. It uses a **hybrid, staged strategy** — lossless first, then
progressively more aggressive lossy fallback — instead of jumping straight to
lossy compression.

Every processed image satisfies two hard guarantees:

```
optimized_size <= target_size
optimized_size <= original_size
```

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [API](#api)
- [Target Sizes & Dimension Constraints](#target-sizes--dimension-constraints)
- [Supported Formats](#supported-formats)
- [Responsive Image Variants](#responsive-image-variants)
- [Compression Pipeline](#compression-pipeline)
- [Compression Methods](#compression-methods)
- [Model Fields](#model-fields)
- [Example Response](#example-response)
- [Design Trade-offs](#design-trade-offs)
- [Testing Checklist](#testing-checklist)

---

## Features

- **Hybrid compression** — lossless → near-lossless → tiered lossy
  (quality-first, then resize) → guaranteed forced-fit last resort
- **Smart lossless strategy** — palette-mode images → guarded octree quantization with color count check (avoids expensive tree allocation on photos) → verified RGBA quantization for transparency → standard PNG deflate → strict lossless WebP
- **Smart lossy fallback** — AVIF-only pipeline: quality search at original dimensions (4:4:4 → 4:2:2 → 4:2:0 subsampling), then progressive resizing (0.9–0.1 scale)
- **Responsive variants** — automatically generate mobile/laptop/desktop versions from optimized result, preserving compression parameters
- **Per-type targets** — thumbnail / logo / regular / hero each have their
  own target size, dimension constraints, and responsive breakpoints
- **Format-aware** — JPEG, PNG, WebP, AVIF, GIF, SVG each get handling
  appropriate to that format
- **Animation-safe** — GIF, SVG, and animated WebP/PNG are returned
  unchanged; flattening an animation would be data loss, not optimization
- **Dimension validation**
  - Below minimum → rejected (upscaling would fabricate pixel data)
  - Above maximum → automatically downscaled proportionally, never rejected
- **Content-sniffed validation** — real file bytes are inspected; the
  filename extension is never trusted
- **Format-flexible output** — the output format may differ from the input
  when it compresses better at equivalent quality (e.g. JPEG → WebP)
- **Storage-lean** — only the final optimized file is persisted; original
  bytes are discarded after their metadata (size, format, filename) is
  recorded
- **Rich metadata** — every upload records the compression method, quality,
  near-lossless level, resize scale, and whether dimensions were auto-capped

---

## Tech Stack

| Component        | Choice                                    |
|-------------------|--------------------------------------------|
| Framework         | Django 6.1 + Django REST Framework 3.18.0  |
| Image processing  | Pillow 12.3.0                              |
| AVIF support      | pillow-avif-plugin 1.6.0                   |
| Database          | SQLite (dev) — swap for Postgres in prod   |

---

## Quick Start

```bash
# 1. Clone and create a virtual environment
git clone https://github.com/Shahriar-Hasan123/Image-Optimizer.git
cd image_optimizer
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Migrate and run
python manage.py migrate
python manage.py runserver
```

### Try it with Postman / curl

```
POST http://127.0.0.1:8000/api/images/
Content-Type: multipart/form-data

image_file  → file
image_type  → one of: thumbnail | logo | regular | hero
```

```bash
curl -X POST http://127.0.0.1:8000/api/images/ \
  -F "image_file=@photo.jpg" \
  -F "image_type=regular"
```

---

## API

| Method | Endpoint             | Description                     |
|--------|-----------------------|----------------------------------|
| `GET`    | `/api/images/`        | List all processed uploads       |
| `POST`   | `/api/images/`        | Upload and compress an image     |
| `GET`    | `/api/images/<id>/`   | Retrieve a single upload's record|
| `DELETE` | `/api/images/<id>/`   | Delete an upload                 |

---

## Target Sizes & Dimension Constraints

| Image Type | Target Size | Min (W×H) | Max (W×H)   |
|------------|------------:|-----------|-------------|
| Thumbnail  | 50 KB       | 50×50     | 800×800     |
| Logo       | 100 KB      | 50×50     | 1000×1000   |
| Regular    | 500 KB      | 200×200   | 4000×4000   |
| Hero       | 800 KB      | 1200×400  | 6000×4000   |

Exceeding the maximum always auto-resizes proportionally (never rejected).
Falling below the minimum is always rejected — upscaling would fabricate
pixel data and reduce quality.

---

## Supported Formats

| Format | Compression Behavior                                            |
|--------|-------------------------------------------------------------------|
| JPEG   | Treated as already-lossy source, goes straight to the lossy step  |
| PNG    | Full lossless → near-lossless → lossy cascade                     |
| WebP   | Full lossless → near-lossless → lossy cascade                     |
| AVIF   | Treated as already-lossy source (documented simplifying assumption) |
| GIF    | Returned unchanged, no compression attempted                      |
| SVG    | Returned unchanged, no compression attempted (validated as real XML/SVG) |

> **Note on AVIF:** AVIF *can* be losslessly encoded, but a decoded frame in
> Pillow carries no reliable flag indicating whether the source was lossless
> or lossy. Since the large majority of real-world AVIF files are lossy,
> this service treats AVIF sources as already-lossy to avoid wasted
> computation — a deliberate, documented trade-off, not an oversight.

---

## Responsive Image Variants

After primary optimization, the service **automatically generates responsive variants** (mobile, laptop, desktop) from the compressed result:

| Image Type | Mobile | Laptop | Desktop |
|------------|--------|--------|---------|
| Thumbnail  | 150 px | 300 px | 400 px  |
| Logo       | 120 px | 200 px | 300 px  |
| Regular    | 480 px | 1366 px| 1920 px |
| Hero       | 480 px | 1600 px| 1920 px |

**Key behaviors:**
- Skipped entirely for GIF/SVG/animated images (no upscaling of data-loss formats)
- Skips any breakpoint where target width ≥ optimized image width (never upscale)
- Preserves the **exact compression method and quality parameters** from the primary result
- Generated variants stored as separate `ImageVariant` records linked to the primary image
- Filenames prefixed with variant type: `mobile_photo.webp`, `laptop_photo.webp`, etc.

This enables responsive image delivery without re-compressing or quality loss.

---

## Compression Pipeline

Each stage is tried **at most once** — no candidate is generated twice — and
stages are ordered by increasing perceptual cost, so quality is only
sacrificed after every gentler option has been exhausted.

```
Upload received
      │
      ▼
Content-based format sniff (never trust extension)
      │
      ▼
GIF / SVG / animated WebP-PNG? ──yes──► return unchanged ──► DONE
      │ no
      ▼
Dimension validation
  below min → reject
  above max → auto-resize proportionally
      │
      ▼
original_size <= target_size? ──yes──► return unchanged ──► DONE
      │ no
      ▼
Source already lossy (JPEG / AVIF)?
      │                       │
     yes                      no
      │                       ▼
      │              STEP 0 — Lossless Cascade
      │              1. Native palette mode (mode P) → PNG optimize
      │              2. Guarded RGBA quantization with color count check
      │                 (fast bitmap returns None if >256 colors, skips expensive octree)
      │              3. Verified lossless quantization pass if ≤256 colors
      │              4. Standard DEFLATE PNG compress_level=9
      │              5. Strict lossless WebP (method=6, exact=True)
      │                       │
      │              fits target? ──yes──► DONE
      │                       │ no
      │                       ▼
      │              STEP 1 — Near-lossless
      │              WebP near_lossless levels: 95, 90, 85, 80, 75
      │                       │
      │              fits target? ──yes──► DONE
      │                       │ no
      └───────────────────────┤
                               ▼
                  STEP 2 — Lossy (AVIF-only pipeline with binary search)
                    2a. Subsampling priority at original dimensions:
                        4:4:4 (sharpest) → 4:2:2 (balanced) → 4:2:0 (maximum compression)
                        with quality binary search for each
                    2b. Progressive resizing fallback (4:2:0 subsampling only):
                        scales 0.9 → 0.8 → 0.7 → ... → 0.1 with quality search
                               │
                  fits target? ──yes──► DONE
                               │ no
                               ▼
                  STEP 3 — Forced fit (guaranteed)
                    0.1 scale + minimum quality
                               │
                               ▼
                  Post-compression validation
                    optimized_size <= target_size   (enforced)
                    optimized_size <= original_size  (enforced)
                    width / height valid             (enforced)
                               │
                               ▼
                          DONE — saved
```

---

## Compression Methods

Returned in the API response under `method`.

| Method          | Meaning                                                        |
|------------------|------------------------------------------------------------------|
| `not_needed`     | Original already fit the target — untouched                     |
| `skipped`        | GIF / SVG / animated image — untouched                           |
| `lossless`       | Pixel-identical recompression: native palette mode, verified RGBA quantization for transparency (with fast color count check to avoid expensive tree allocation on photos), standard PNG deflate, or WebP lossless |
| `near_lossless`  | WebP near-lossless smoothing — imperceptible quality cost        |
| `lossy`          | AVIF quality-only compression at original dimensions with subsampling search (4:4:4 → 4:2:2 → 4:2:0) |
| `lossy_resized`  | AVIF progressive resizing with quality search (0.9 → 0.1 scale, 4:2:0 subsampling) |
| `forced_fit`     | Last-resort: extreme downscaling (0.1 scale) + minimum quality (AVIF) |

---

## Model Fields

### ImageUpload (primary record)

| Field | Description |
|-------|-------------|
| `image_type` | `thumbnail` / `logo` / `regular` / `hero` |
| `image` | Final optimized file (the only file actually stored) |
| `original_filename`, `original_format`, `original_size` | Metadata only — original bytes are not persisted |
| `optimized_format`, `optimized_size` | Result of compression |
| `target_size` | Target for this `image_type` at time of upload |
| `original_width`, `original_height` | As-uploaded dimensions |
| `optimized_width`, `optimized_height` | Final dimensions after any resizing |
| `dimension_capped` | `true` if auto-resized for exceeding max dimensions |
| `method` | Which compression stage produced the result |
| `quality`, `near_lossless_level`, `scale` | Stage-specific parameters used |
| `compression_ratio` | Computed: `1 - (optimized_size / original_size)` |
| `created_at` | Upload timestamp |

### ImageVariant (responsive breakpoints, linked to ImageUpload)

| Field | Description |
|-------|-------------|
| `image_upload` | Foreign key to parent ImageUpload |
| `variant_type` | `mobile` / `laptop` / `desktop` |
| `image` | Resized variant file |
| `width`, `height` | Variant dimensions (never upscaled from optimized parent) |
| `format` | Output format (mirrors parent's compression method) |
| `file_size` | Variant file size in bytes |
| `created_at` | Generation timestamp |

---

## Example Response

```json
{
    "id": 24,
    "image": "/media/uploads/1_photo.avif",
    "original_filename": "photo.jpg",
    "original_format": "JPEG",
    "optimized_format": "AVIF",
    "original_size": 2284979,
    "original_size_display": "2.18 MB",
    "optimized_size": 468851,
    "optimized_size_display": "457.86 KB",
    "target_size": 512000,
    "target_size_display": "500.00 KB",
    "original_width": 3750,
    "original_height": 2500,
    "optimized_width": 3750,
    "optimized_height": 2500,
    "dimension_capped": false,
    "method": "lossy",
    "quality": 44,
    "near_lossless_level": null,
    "scale": null,
    "compression_ratio": 0.7948,
    "variants": [
        {
            "variant_type": "mobile",
            "image": "/media/uploads/variants/1_mobile_photo.avif",
            "width": 480,
            "height": 320,
            "format": "AVIF",
            "file_size": 17348,
            "file_size_display": "16.94 KB"
        },
        {
            "variant_type": "laptop",
            "image": "/media/uploads/variants/1_laptop_photo.avif",
            "width": 1366,
            "height": 911,
            "format": "AVIF",
            "file_size": 88858,
            "file_size_display": "86.78 KB"
        },
        {
            "variant_type": "desktop",
            "image": "/media/uploads/variants/1_desktop_photo.avif",
            "width": 1920,
            "height": 1280,
            "format": "AVIF",
            "file_size": 151229,
            "file_size_display": "147.68 KB"
        }
    ],
    "created_at": "2026-08-18T11:30:58.877220Z"
}
```

---

## Design Trade-offs

- **No original file retained** — saves storage cost, but means
  re-compression with a future/better pipeline can only work from the
  already-compressed version, not a pristine original.
- **Color count check before quantization** — fast bitmap palette check returns
  instantly (O(n) with early exit at 257 colors) for photos/high-color images,
  avoiding expensive octree quantization tree allocation and ImageChops diff
  on images that won't compress to 256 colors anyway. Trade-off: genuine 256-color
  images still require quantization cost, but photos are protected from worst-case overhead.
- **AVIF treated as always-lossy on input** — avoids wasted lossless attempts
  on the common case, at the cost of missing lossless-encoded AVIF sources
  (rare in practice).
- **`forced_fit` can degrade quality significantly** — only reached for
  extreme cases (very small target vs. very high-detail image), but the
  target-size guarantee takes priority over quality at that point, since it
  is a hard requirement.
- **No upscaling of variants** — responsive variants are only generated at
  smaller breakpoints (never upscaled), protecting image quality by skipping
  breakpoints where the target width would enlarge the optimized result.

---

## Testing Checklist

- [ ] Large JPEG upload as `regular` → `optimized_size <= 512000`
- [ ] Small PNG already under target → `method == "not_needed"`
- [ ] Animated WebP upload → `method == "skipped"`, unchanged
- [ ] SVG with fake `.svg` extension but non-SVG bytes → rejected at validation
- [ ] Oversized dimensions for `thumbnail` → `dimension_capped: true`, resized proportionally
- [ ] High-color RGB image (>256 colors) → quantization color count check avoids expensive tree allocation
- [ ] Transparent PNG with ≤256 unique colors → verified RGBA quantization to lossless
- [ ] Responsive variants generated → mobile/laptop/desktop variants exist with correct widths
- [ ] Variant upscaling prevented → no variants generated for breakpoints ≥ optimized image width
