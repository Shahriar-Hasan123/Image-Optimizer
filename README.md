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
- **Smart lossy fallback** — tries AVIF quality-only, then AVIF with progressive resizing,
  then WebP quality-only, then WebP with progressive resizing, finally forced-fit
- **Per-type targets** — thumbnail / logo / regular / hero each have their
  own target size and dimension constraints
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
      │              STEP 0 — Lossless
      │              PNG optimize / WebP lossless / verified quantize
      │                       │
      │              fits target? ──yes──► DONE
      │                       │ no
      │                       ▼
      │              STEP 1 — Near-lossless
      │              WebP near_lossless, levels 80 → 60 → 40 → 20
      │                       │
      │              fits target? ──yes──► DONE
      │                       │ no
      └───────────────────────┤
                               ▼
                  STEP 2 — Lossy (tiered, quality before resize)
                    2a. AVIF: quality-only at original dimensions
                    2b. AVIF: progressive resize (0.9 → 0.1) + quality search
                    2c. WebP: quality-only at original dimensions
                    2d. WebP: progressive resize (0.9 → 0.1) + quality search
                               │
                  fits target? ──yes──► DONE
                               │ no
                               ▼
                  STEP 3 — Forced fit (guaranteed)
                    WebP at 0.1 scale, quality 1
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
| `lossless`       | Pixel-identical recompression (PNG optimize / verified quantize / WebP lossless) |
| `near_lossless`  | WebP near-lossless smoothing — imperceptible quality cost        |
| `lossy`          | Quality-only compression at original dimensions                 |
| `lossy_resized`  | Quality + progressive resizing fallback (0.9 → 0.1 scale)       |
| `lossy_forced_fit` | Last-resort: extreme downscaling (0.1 scale) + minimum quality  |

---

## Model Fields

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
| `created_at` | Upload timestamp |

---

## Example Response

```json
{
  "id": 12,
  "image": "/media/uploads/2026/08/13/photo.webp",
  "original_filename": "photo.jpg",
  "original_format": "JPEG",
  "optimized_format": "WEBP",
  "original_size": 2456000,
  "original_size_display": "2.34 MB",
  "optimized_size": 487213,
  "optimized_size_display": "475.79 KB",
  "target_size": 512000,
  "target_size_display": "500.00 KB",
  "original_width": 3000,
  "original_height": 2000,
  "optimized_width": 2400,
  "optimized_height": 1600,
  "dimension_capped": false,
  "method": "lossy_resized",
  "quality": 82,
  "scale": 0.8,
  "compression_ratio": 0.8016
}
```

---

## Design Trade-offs

- **No original file retained** — saves storage cost, but means
  re-compression with a future/better pipeline can only work from the
  already-compressed version, not a pristine original.
- **AVIF treated as always-lossy on input** — avoids wasted lossless attempts
  on the common case, at the cost of missing lossless-encoded AVIF sources
  (rare in practice).
- **`forced_fit` can degrade quality significantly** — only reached for
  extreme cases (very small target vs. very high-detail image), but the
  target-size guarantee takes priority over quality at that point, since it
  is a hard requirement.

---

## Testing Checklist

- [ ] Large JPEG upload as `regular` → `optimized_size <= 512000`
- [ ] Small PNG already under target → `method == "not_needed"`
- [ ] Animated WebP upload → `method == "skipped"`, unchanged
- [ ] SVG with fake `.svg` extension but non-SVG bytes → rejected at validation
- [ ] Oversized dimensions for `thumbnail` → `dimension_capped: true`, resized proportionally
