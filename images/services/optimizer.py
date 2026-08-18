import io
from PIL import Image, ImageOps
import pillow_avif  # noqa: F401 — registers AVIF codec with Pillow

from ..constants import (
    TARGET_SIZES,
    DIMENSION_CONSTRAINTS,
    ALREADY_LOSSY_SOURCE,
    SKIP_FORMATS,
)
from ..result import CompressionResult
from .lossless import try_lossless
from .lossy import compress_lossy


def _has_transparency(img: Image.Image) -> bool:
    if "A" in img.getbands():
        return img.getchannel("A").getextrema()[0] < 255
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def _clamp_to_max_dimensions(img: Image.Image, image_type: str):
    """
    Downscale proportionally if the image exceeds this type's max width/height.
    """
    c = DIMENSION_CONSTRAINTS[image_type]
    w, h = img.size
    if w <= c["max_w"] and h <= c["max_h"]:
        return img, False
    scale = min(c["max_w"] / w, c["max_h"] / h)  # preserves aspect ratio
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS), True


def compress_image(
    file, image_type: str, fmt: str, is_animated: bool
) -> CompressionResult:
    """
    Single entry point for the whole pipeline. Contract:
      - optimized_size <= TARGET_SIZES[image_type]
      - optimized_size <= original_size
      - width/height never exceed max constraint
      - GIF / SVG / animated WEBP-PNG returned unchanged
    """
    original_name = file.name
    base_name = (
        original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    )
    file.seek(0)
    original_bytes = file.read()
    original_size = len(original_bytes)
    target_bytes = TARGET_SIZES[image_type]

    # GIF / SVG / animated WEBP or PNG — returned unchanged.
    if fmt in SKIP_FORMATS or is_animated:
        return CompressionResult(
            data=original_bytes,
            filename=original_name,
            format=fmt,
            method="skipped",
            original_size=original_size,
            optimized_size=original_size,
            target_size=target_bytes,
        )

    file.seek(0)
    with Image.open(file) as opened:
        opened.load()
        img = ImageOps.exif_transpose(
            opened.copy()
        )  # correct orientation, drops EXIF as a side effect

    orig_w, orig_h = img.size

    # Clamp dimensions first (if required by configuration)
    img, dimension_capped = _clamp_to_max_dimensions(img, image_type)

    # Already under target AND within max dimensions — return original
    if original_size <= target_bytes and not dimension_capped:
        return CompressionResult(
            data=original_bytes,
            filename=original_name,
            format=fmt,
            method="not_needed",
            original_size=original_size,
            optimized_size=original_size,
            target_size=target_bytes,
            original_width=orig_w,
            original_height=orig_h,
            optimized_width=orig_w,
            optimized_height=orig_h,
            dimension_capped=False,
        )

    has_alpha = _has_transparency(img)
    result = None

    # Step 1: Pass untouched original img (preserves mode="P", "L", etc.) to try_lossless
    if fmt not in ALREADY_LOSSY_SOURCE:
        data, out_fmt, method, extra, hit = try_lossless(img, target_bytes)
        if hit:
            result = _finalize(
                data,
                base_name,
                out_fmt,
                method,
                extra,
                original_size,
                target_bytes,
                orig_w,
                orig_h,
                dimension_capped,
            )

    # Step 2: Fallback to Lossy Compression (Normalize mode to RGBA/RGB explicitly for lossy encoders)
    if result is None:
        working_img = img.convert("RGBA" if has_alpha else "RGB")
        data, out_fmt, method, extra = compress_lossy(
            working_img, target_bytes
        )
        result = _finalize(
            data,
            base_name,
            out_fmt,
            method,
            extra,
            original_size,
            target_bytes,
            orig_w,
            orig_h,
            dimension_capped,
        )

    # --- Post-compression validation ---

    # 1. If optimization made the image larger, fallback ONLY if original actually fits target
    if result.optimized_size >= original_size and not dimension_capped:
        if original_size <= target_bytes:
            return CompressionResult(
                data=original_bytes,
                filename=original_name,
                format=fmt,
                method="fallback_original",
                original_size=original_size,
                optimized_size=original_size,
                target_size=target_bytes,
                original_width=orig_w,
                original_height=orig_h,
                optimized_width=orig_w,
                optimized_height=orig_h,
                dimension_capped=False,
            )

    # 2. Enforce strict target size contract
    if not result.meets_target():
        raise RuntimeError(
            f"Target guarantee violated: optimized {result.optimized_size} bytes "
            f"> target {target_bytes} bytes for '{original_name}'."
        )

    # 3. Enforce smaller-than-original rule if original did not meet target
    if not result.is_smaller_than_original() and not dimension_capped:
        raise RuntimeError(
            f"Optimization produced a larger file ({result.optimized_size} bytes) "
            f"than original ({result.original_size} bytes) for '{original_name}'."
        )

    if result.optimized_width <= 0 or result.optimized_height <= 0:
        raise RuntimeError(
            f"Invalid optimized dimensions {result.optimized_width}x{result.optimized_height} "
            f"for '{original_name}'."
        )

    return result


def _finalize(
    data,
    base_name,
    fmt,
    method,
    extra,
    original_size,
    target_bytes,
    orig_w,
    orig_h,
    dimension_capped,
):
    ext = {"PNG": ".png", "WEBP": ".webp", "JPEG": ".jpg", "AVIF": ".avif"}[fmt]

    with Image.open(io.BytesIO(data)) as final_img:
        opt_w, opt_h = final_img.size

    return CompressionResult(
        data=data,
        filename=f"{base_name}{ext}",
        format=fmt,
        method=method,
        original_size=original_size,
        optimized_size=len(data),
        target_size=target_bytes,
        original_width=orig_w,
        original_height=orig_h,
        optimized_width=opt_w,
        optimized_height=opt_h,
        dimension_capped=dimension_capped,
        **extra,
    )
