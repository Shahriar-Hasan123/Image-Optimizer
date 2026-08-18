import io
from PIL import Image

from ..constants import RESIZE_SCALE_STEPS, FORCED_FIT_SCALE

# Speed 6 is fast for searching; Speed 2 is highly efficient for production saves without CPU locks
AVIF_SEARCH_SPEED = 6
AVIF_FINAL_SPEED = 2

# Enforce strict quality bounds to protect zoom fidelity
QUALITY_MIN = 1
QUALITY_MAX = 95

# Search order: 4:4:4 preserves sharp text/edges, 4:2:2 balances detail, 4:2:0 maximizes compression
SUBSAMPLING_CANDIDATES = ("4:4:4", "4:2:2", "4:2:0")


def _encode_avif(img: Image.Image, quality: int, speed: int, subsampling: str) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="AVIF", quality=quality, speed=speed, subsampling=subsampling)
    return buf.getvalue()


def _binary_search_quality(
    img: Image.Image, target_bytes: int, encode_fn, q_min=QUALITY_MIN, q_max=QUALITY_MAX
):
    """Finds highest quality (>= QUALITY_MIN) whose encoded size <= target_bytes."""

    low, high, best = q_min, q_max, None
    while low <= high:
        mid = (low + high) // 2
        data = encode_fn(img, mid)
        if len(data) <= target_bytes:
            best = (mid, data)
            low = mid + 1
        else:
            high = mid - 1
    return best


def _search_at_dimensions(img: Image.Image, target_bytes: int):
    """Try each subsampling candidate at current dimensions, prioritizing 4:4:4."""

    for subsampling in SUBSAMPLING_CANDIDATES:
        result = _binary_search_quality(
            img,
            target_bytes,
            lambda im, q, ss=subsampling: _encode_avif(im, q, AVIF_SEARCH_SPEED, ss),
        )
        if result:
            quality, search_data = result
            data = _encode_avif(img, quality, AVIF_FINAL_SPEED, subsampling)

            # Guard against edge-case encoder size shifts at lower speed
            if len(data) > target_bytes:
                data = search_data

            if len(data) <= target_bytes:
                return data, quality, subsampling

    return None


def _try_resize_fallback(img: Image.Image, target_bytes: int):
    """Progressively smaller scales using 4:2:0 subsampling."""

    for scale in RESIZE_SCALE_STEPS:
        w, h = img.size
        new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))

        # Resample once using Lanczos to preserve edge sharpness
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Early check: If min acceptable quality (70) at this scale is still too big, skip to smaller scale
        min_quality_data = _encode_avif(
            resized, QUALITY_MIN, AVIF_SEARCH_SPEED, "4:2:0"
        )
        if len(min_quality_data) > target_bytes:
            continue

        result = _binary_search_quality(
            resized,
            target_bytes,
            lambda im, q: _encode_avif(im, q, AVIF_SEARCH_SPEED, "4:2:0"),
        )
        if result:
            quality, search_data = result
            data = _encode_avif(resized, quality, AVIF_FINAL_SPEED, "4:2:0")
            if len(data) > target_bytes:
                data = search_data
            return data, quality, scale

    return None


def compress_lossy(img: Image.Image, target_bytes: int):
    """AVIF compression prioritized for zoom preservation and byte budget targeting."""

    try:
        # 1. High-fidelity pass (Original dimensions + 4:4:4 / 4:2:2 / 4:2:0 search)
        result = _search_at_dimensions(img, target_bytes)
        if result:
            data, quality, subsampling = result
            return (
                data,
                "AVIF",
                "lossy",
                {"quality": quality, "subsampling": subsampling},
            )

        # 2. Resampling fallback
        result = _try_resize_fallback(img, target_bytes)
        if result:
            data, quality, scale = result
            return (
                data,
                "AVIF",
                "lossy_resized",
                {"quality": quality, "subsampling": "4:2:0", "scale": scale},
            )
            
        # 3. Exceeded target_bytes — target is unreachable for this image.
        raise RuntimeError(
            f"Could not reach target size ({target_bytes} bytes) even at "
            f"minimum quality and smallest scale ({RESIZE_SCALE_STEPS[-1]})."
        )

    except Exception as e:
        raise RuntimeError(f"Lossy compression failed: {e}") from e
