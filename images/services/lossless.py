import io
from PIL import Image, ImageChops

from ..constants import NEAR_LOSSLESS_LEVELS


def _encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _is_lossless_quantize(source: Image.Image, quantized: Image.Image) -> bool:
    """Verify that quantization produces pixel-identical output."""
    if source.size != quantized.size:
        return False

    try:
        reconstructed = quantized.convert(source.mode)
    except (ValueError, OSError):
        return False

    diff = ImageChops.difference(source, reconstructed)
    return diff.getbbox() is None


def try_lossless(img: Image.Image, target_bytes: int):
    """
    Try strict lossless image optimization first.

    Returns:
        (best_bytes, best_fmt, method, extra, hit_target)
    """
    candidates = []
    palette_found = False

    # 1. Fast-path: Native palette images (mode P)
    if img.mode == "P":
        try:
            data = _encode(img, "PNG", optimize=True, compress_level=9)
            candidates.append((data, "PNG", "lossless", {}))
            palette_found = True
        except (ValueError, OSError):
            pass

    # 2. Guarded quantization pass for non-palette images (RGB, RGBA, L)
    elif img.mode in ("RGB", "RGBA", "L"):
        # Fast color count check:
        # Returns None instantly if distinct color count > 256.
        # Avoids allocating quantization trees & running ImageChops diff on photos.
        colors = img.getcolors(maxcolors=257)

        if colors is not None and len(colors) <= 256:
            try:
                quantized = img.quantize(
                    colors=256,
                    method=Image.Quantize.FASTOCTREE,
                    dither=Image.Dither.NONE,
                )

                # Confirm zero visual/alpha loss
                if _is_lossless_quantize(img, quantized):
                    data = _encode(quantized, "PNG", optimize=True, compress_level=9)
                    candidates.append((data, "PNG", "lossless", {}))
                    palette_found = True
            except (ValueError, OSError):
                pass

    # 3. Standard DEFLATE PNG (Skipped if a lossless palette pass succeeded)
    if not palette_found:
        try:
            png_data = _encode(
                img,
                "PNG",
                optimize=True,
                compress_level=9,
            )
            candidates.append((png_data, "PNG", "lossless", {}))
        except (ValueError, OSError):
            pass

    # 4. Strict Lossless WebP
    try:
        webp_data = _encode(
            img,
            "WEBP",
            lossless=True,
            method=6,
            exact=True,  # Preserves hidden RGB vectors under zero-alpha pixels
        )
        candidates.append((webp_data, "WEBP", "lossless", {}))
    except (ValueError, OSError):
        pass

    if not candidates:
        raise ValueError("Unable to encode image using lossless formats")

    # Pick smallest candidate so far
    candidates.sort(key=lambda candidate: len(candidate[0]))
    best = candidates[0]

    # Return early if strict lossless hits target
    if len(best[0]) <= target_bytes:
        return (best[0], best[1], best[2], best[3], True)

    # 5. Near-lossless WebP fallback
    for level in NEAR_LOSSLESS_LEVELS:
        try:
            data = _encode(
                img,
                "WEBP",
                lossless=True,
                near_lossless=level,
                method=6,
            )
        except (ValueError, OSError):
            continue

        candidate = (
            data,
            "WEBP",
            "near_lossless",
            {"near_lossless_level": level},
        )

        if len(data) <= target_bytes:
            return (candidate[0], candidate[1], candidate[2], candidate[3], True)

        if len(data) < len(best[0]):
            best = candidate

    return (best[0], best[1], best[2], best[3], False)
