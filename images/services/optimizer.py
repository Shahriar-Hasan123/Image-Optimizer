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
    return img.resize(new_size, Image.LANCZOS), True


def compress_image(
    file, image_type: str, fmt: str, is_animated: bool
) -> CompressionResult:
    """
    Single entry point for the whole pipeline. Contract:
      - optimized_size <= TARGET_SIZES[image_type]      (enforced, never silent)
      - optimized_size <= original_size                  (enforced, never silent)
      - width/height never exceed this type's max constraint (auto-capped, flagged)
      - GIF / SVG / animated WEBP-PNG returned unchanged
      - if original already fits target, returned unchanged
      - lossy output is always WEBP or AVIF, never JPEG (see lossy.py)
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

    img, dimension_capped = _clamp_to_max_dimensions(img, image_type)

    # Already under target AND within max dimensions — nothing to do at all.
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
    working_img = img.convert("RGBA" if has_alpha else "RGB")

    result = None

    # JPEG/AVIF sources are treated as already-lossy: re-attempting a lossless
    
    if fmt not in ALREADY_LOSSY_SOURCE:
        data, out_fmt, method, extra, hit = try_lossless(working_img, target_bytes)
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

    if result is None:
        data, out_fmt, method, extra = compress_lossy(
            working_img, target_bytes, has_alpha
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
    
    if not result.meets_target():
        raise RuntimeError(
            f"Target guarantee violated: optimized {result.optimized_size} bytes "
            f"> target {target_bytes} bytes for '{original_name}'."
        )
    if not result.is_smaller_than_original():
        raise RuntimeError(
            f"Optimization produced a larger file: optimized={result.optimized_size} "
            f"> original={result.original_size} for '{original_name}'. Pipeline bug."
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

    # Read actual dimensions back from the encoded bytes — ground truth
    # regardless of which step (max-clamp, lossless, or lossy-resize) produced
    # the result, so no extra width/height plumbing is needed elsewhere.
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
