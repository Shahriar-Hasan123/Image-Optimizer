import io
from PIL import Image

from ..constants import RESIZE_SCALE_STEPS, FORCED_FIT_SCALE

AVIF_SEARCH_SPEED = 6
AVIF_FINAL_SPEED = 0
QUALITY_MIN = 1
QUALITY_MAX = 95


def _encode_avif(img: Image.Image, quality: int, speed: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="AVIF", quality=quality, speed=speed)
    return buf.getvalue()


def _encode_webp(img: Image.Image, quality: int, method: int = 6) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=method)
    return buf.getvalue()


def _binary_search_quality(
    img, target_bytes, encode_fn, q_min=QUALITY_MIN, q_max=QUALITY_MAX
):
    """Highest quality whose encoded size <= target, at current dimensions."""
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


def _try_resize_fallback(img: Image.Image, target_bytes: int, encode_fn):
    """Try progressively smaller scales to fit target."""
    
    scales = list(RESIZE_SCALE_STEPS) + [FORCED_FIT_SCALE]
    
    for scale in scales:
        w, h = img.size
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        
        result = _binary_search_quality(resized, target_bytes, encode_fn)
        if result:
            quality, data = result
            return data, quality, scale
    
    return None


def compress_lossy(img: Image.Image, target_bytes: int, has_alpha: bool):
    """AVIF-primary with resize fallback when quality-only fails."""
    try:
        # Step 1: Quality-only at original dimensions
        result = _binary_search_quality(
            img, target_bytes, lambda im, q: _encode_avif(im, q, AVIF_SEARCH_SPEED)
        )
        if result:
            quality, search_data = result
            data = _encode_avif(img, quality, AVIF_FINAL_SPEED)
            if len(data) > target_bytes:
                data = search_data
            if len(data) <= target_bytes:
                return data, "AVIF", "lossy", {"quality": quality}

        # Step 2: Resize fallback for AVIF
        result = _try_resize_fallback(
            img, target_bytes, lambda im, q: _encode_avif(im, q, AVIF_FINAL_SPEED)
        )
        if result:
            data, quality, scale = result
            if len(data) <= target_bytes:
                return data, "AVIF", "lossy_resized", {"quality": quality, "scale": scale}

        # Step 3: Quality-only WebP
        result = _binary_search_quality(
            img, target_bytes, lambda im, q: _encode_webp(im, q, method=4)
        )
        if result:
            quality, search_data = result
            data = _encode_webp(img, quality, method=6)
            if len(data) > target_bytes:
                data = search_data
            if len(data) <= target_bytes:
                return data, "WEBP", "lossy", {"quality": quality}

        # Step 4: Resize fallback for WebP
        result = _try_resize_fallback(
            img, target_bytes, lambda im, q: _encode_webp(im, q, method=6)
        )
        if result:
            data, quality, scale = result
            if len(data) <= target_bytes:
                return data, "WEBP", "lossy_resized", {"quality": quality, "scale": scale}

        # Fallback: return smallest WEBP at minimum scale
        w, h = img.size
        new_w = max(1, int(w * FORCED_FIT_SCALE))
        new_h = max(1, int(h * FORCED_FIT_SCALE))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        data = _encode_webp(resized, QUALITY_MIN, method=6)
        return data, "WEBP", "lossy_forced_fit", {"quality": QUALITY_MIN, "scale": FORCED_FIT_SCALE}

    except Exception as e:
        raise RuntimeError(f"Lossy compression failed: {e}")
