import io
from PIL import Image
from ..constants import (
    QUALITY_HIGH_FLOOR,
    QUALITY_FLOOR_SOFT,
    QUALITY_FLOOR_HARD,
    RESIZE_SCALE_STEPS,
    FORCED_FIT_SCALE,
)

AVIF_SEARCH_SPEED = 6  # faster trial encodes during binary search
AVIF_FINAL_SPEED = 0  # best compression — used once, on the winning candidate


def _encode_avif(img: Image.Image, quality: int, speed: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="AVIF", quality=quality, speed=speed)
    return buf.getvalue()


def _encode_webp(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def _resize(img: Image.Image, scale: float) -> Image.Image:
    if scale >= 0.999:
        return img
    w, h = img.size
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _binary_search_quality(img, target_bytes, q_min, q_max=95, speed=AVIF_SEARCH_SPEED):
    low, high, best = q_min, q_max, None
    while low <= high:
        mid = (low + high) // 2
        data = _encode_avif(img, mid, speed)
        if len(data) <= target_bytes:
            best = (mid, data)
            low = mid + 1
        else:
            high = mid - 1
    return best


def _finalize_avif(candidate, quality, search_bytes, target_bytes):
    """Re-encode the winning candidate at best-compression speed, but verify
    it still fits — speed=0 isn't guaranteed to be <= speed=6 in size for
    every image, so we can't blindly trust it."""
    data = _encode_avif(candidate, quality, AVIF_FINAL_SPEED)
    if len(data) <= target_bytes:
        return data
    # Fell back on the re-encode — the speed=6 bytes from the search already
    # verified <= target_bytes, so use those instead of overshooting.
    return search_bytes


def compress_lossy(img: Image.Image, target_bytes: int, has_alpha: bool):
    """
    AVIF-primary: AVIF wins the vast majority of quality-per-byte comparisons
    against WEBP/JPEG (see prior benchmarks — ~15-40% fewer bytes at equal
    quality), so this skips exhaustive per-format comparison and searches
    AVIF directly. WEBP is only used as a fallback if AVIF encoding fails
    on a given image (rare codec/mode edge cases).

    Search priority: quality is degraded before resolution. For each scale
    (starting at full size), we exhaust the quality tiers before shrinking
    further — a full-res image at lower quality is preferred over a
    downscaled image at higher quality, since resizing is the more visible
    quality hit for most content.
    """
    quality_tiers = [QUALITY_HIGH_FLOOR, QUALITY_FLOOR_SOFT, QUALITY_FLOOR_HARD]
    scales = [1.0] + list(RESIZE_SCALE_STEPS)

    try:
        for scale in scales:
            candidate = _resize(img, scale)
            for i, q_floor in enumerate(quality_tiers):
                # q_max caps at the previous tier's floor so we never re-search
                # a quality range we already tried and failed at this scale.
                q_max = quality_tiers[i - 1] - 1 if i > 0 else 95
                if q_max < q_floor:
                    continue
                result = _binary_search_quality(candidate, target_bytes, q_min=q_floor, q_max=q_max)
                if result:
                    quality, search_bytes = result
                    data = _finalize_avif(candidate, quality, search_bytes, target_bytes)
                    method = "lossy" if scale == 1.0 else "lossy_resized"
                    extra = {"quality": quality}
                    if scale < 0.999:
                        extra["scale"] = round(scale, 2)
                    return data, "AVIF", method, extra

        # Forced fit — guaranteed
        resized = _resize(img, FORCED_FIT_SCALE)
        data = _encode_avif(resized, QUALITY_FLOOR_HARD, AVIF_FINAL_SPEED)
        quality = QUALITY_FLOOR_HARD
        if len(data) > target_bytes:
            data = _encode_avif(resized, 1, AVIF_FINAL_SPEED)
            quality = 1
        return (
            data,
            "AVIF",
            "forced_fit",
            {"quality": quality, "scale": FORCED_FIT_SCALE},
        )

    except Exception:
        # AVIF failed on this image — fall back to the WEBP-only cascade
        return _compress_lossy_webp_fallback(img, target_bytes)


def _compress_lossy_webp_fallback(img: Image.Image, target_bytes: int):
    quality_tiers = [QUALITY_HIGH_FLOOR, QUALITY_FLOOR_SOFT, QUALITY_FLOOR_HARD]
    scales = [1.0] + list(RESIZE_SCALE_STEPS)

    for scale in scales:
        candidate = _resize(img, scale)
        for i, q_floor in enumerate(quality_tiers):
            q_max = quality_tiers[i - 1] - 1 if i > 0 else 95
            if q_max < q_floor:
                continue
            low, high, best = q_floor, q_max, None
            while low <= high:
                mid = (low + high) // 2
                data = _encode_webp(candidate, mid)
                if len(data) <= target_bytes:
                    best = (mid, data)
                    low = mid + 1
                else:
                    high = mid - 1
            if best:
                quality, data = best
                method = "lossy" if scale == 1.0 else "lossy_resized"
                extra = {"quality": quality}
                if scale < 0.999:
                    extra["scale"] = round(scale, 2)
                return data, "WEBP", method, extra

    resized = _resize(img, FORCED_FIT_SCALE)
    data = _encode_webp(resized, QUALITY_FLOOR_HARD)
    return (
        data,
        "WEBP",
        "forced_fit",
        {"quality": QUALITY_FLOOR_HARD, "scale": FORCED_FIT_SCALE},
    )