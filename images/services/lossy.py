import io
import logging
from PIL import Image

logger = logging.getLogger(__name__)

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
    """Highest quality whose encoded size <= target, at ORIGINAL dimensions only."""
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


def compress_lossy(img: Image.Image, target_bytes: int, has_alpha: bool):
    """
    AVIF-primary, quality-only search — NO resizing anywhere in this
    function, per explicit instructor requirement. Dimensions are never
    altered; only quality is reduced, down to QUALITY_MIN=1 if necessary.

    Trade-off this creates: if even quality=1 at original resolution still
    exceeds target_bytes, the target CANNOT be met without resizing — that
    case is logged clearly and the smallest achievable result is returned
    rather than silently claiming success.
    """
    try:
        result = _binary_search_quality(
            img, target_bytes, lambda im, q: _encode_avif(im, q, AVIF_SEARCH_SPEED)
        )
        if result:
            quality, search_data = result
            data = _encode_avif(img, quality, AVIF_FINAL_SPEED)
            if len(data) > target_bytes:
                data = search_data  # high-effort re-encode grew — use the verified search bytes
            logger.info(
                "AVIF quality-only fit: quality=%s size=%sB target=%sB",
                quality,
                len(data),
                target_bytes,
            )
            return data, "AVIF", "lossy", {"quality": quality}

        # quality=1 still doesn't fit — target cannot be met without resizing
        data = _encode_avif(img, QUALITY_MIN, AVIF_FINAL_SPEED)
        logger.warning(
            "Target NOT met without resizing: quality=1 size=%sB still exceeds target=%sB",
            len(data),
            target_bytes,
        )
        return data, "AVIF", "quality_floor_exceeded", {"quality": QUALITY_MIN}

    except Exception:
        logger.exception("AVIF failed — falling back to WEBP, quality-only, no resize")
        result = _binary_search_quality(
            img, target_bytes, lambda im, q: _encode_webp(im, q, method=4)
        )
        if result:
            quality, _ = result
            data = _encode_webp(img, quality, method=6)
            return data, "WEBP", "lossy", {"quality": quality}
        data = _encode_webp(img, QUALITY_MIN, method=6)
        logger.warning(
            "WEBP fallback also exceeded target at quality=1: size=%sB target=%sB",
            len(data),
            target_bytes,
        )
        return data, "WEBP", "quality_floor_exceeded", {"quality": QUALITY_MIN}
