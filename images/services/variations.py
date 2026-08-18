import io
from PIL import Image
from pathlib import Path

from ..constants import RESPONSIVE_VARIANT_WIDTHS
from ..result import CompressionResult

FALLBACK_QUALITY = 85
_EXT = {"PNG": ".png", "WEBP": ".webp", "JPEG": ".jpg", "AVIF": ".avif"}


def _encode_like_original(
    img: Image.Image, result: CompressionResult
) -> tuple[bytes, str]:
    """
    Re-encode `img` using the same format/params as the main optimized result.
    """
    fmt, method = result.format, result.method
    buf = io.BytesIO()

    # Safely fallback if quality or near_lossless_level are None
    quality = result.quality or FALLBACK_QUALITY
    near_lossless = result.near_lossless_level or 80

    if method in ("lossy", "lossy_resized", "forced_fit") and fmt == "AVIF":
        img.save(buf, format="AVIF", quality=quality, speed=0)
        return buf.getvalue(), "AVIF"

    if method in ("lossy", "lossy_resized", "forced_fit") and fmt == "WEBP":
        img.save(buf, format="WEBP", quality=quality, method=6)
        return buf.getvalue(), "WEBP"

    if method == "near_lossless":
        # WebP near_lossless requires lossless=True in Pillow
        img.save(
            buf,
            format="WEBP",
            lossless=True,
            near_lossless=near_lossless,
            method=6,
        )
        return buf.getvalue(), "WEBP"

    if method == "lossless" and fmt == "PNG":
        img.save(buf, format="PNG", optimize=True, compress_level=9)
        return buf.getvalue(), "PNG"

    if method == "lossless" and fmt == "WEBP":
        img.save(buf, format="WEBP", lossless=True, method=6)
        return buf.getvalue(), "WEBP"

    # Fallback for method == "not_needed" or unrecognized methods
    img.save(buf, format="WEBP", quality=FALLBACK_QUALITY, method=6)
    return buf.getvalue(), "WEBP"


def generate_variants(result: CompressionResult, image_type: str) -> list[dict]:
    """
    Build responsive (mobile/laptop/desktop) variants from an already-optimized
    CompressionResult. Returns dicts ready to construct ImageVariant rows.

    Skips entirely for GIF/SVG/animated sources (result.method == "skipped").
    Skips a breakpoint if its width would upscale the optimized image.
    """
    if result.method == "skipped":
        return []

    breakpoints = RESPONSIVE_VARIANT_WIDTHS[image_type]
    variants = []

    # Extract base name without extension (e.g. "my_image.png" -> "my_image")
    base_name = Path(result.filename).stem

    with Image.open(io.BytesIO(result.data)) as img:
        img.load()
        orig_w, orig_h = img.size

        for variant_type, target_width in breakpoints.items():
            # Never upscale smaller images
            if target_width >= orig_w:
                continue

            scale = target_width / orig_w
            target_height = max(1, round(orig_h * scale))

            # Modern Pillow resampling enum
            resized = img.resize(
                (target_width, target_height), Image.Resampling.LANCZOS
            )

            data, out_format = _encode_like_original(resized, result)

            variants.append(
                {
                    "variant_type": variant_type,
                    "filename": f"{variant_type}_{base_name}{_EXT[out_format]}",
                    "data": data,
                    "width": target_width,
                    "height": target_height,
                    "format": out_format,
                    "file_size": len(data),
                }
            )

    return variants
