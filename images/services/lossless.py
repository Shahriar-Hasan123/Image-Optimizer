import io

from PIL import Image, ImageChops

from ..constants import NEAR_LOSSLESS_LEVELS


def _encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _is_lossless_quantize(
    source: Image.Image,
    quantized: Image.Image,
) -> bool:
    """Verify that quantization produces pixel-identical output."""
    if source.size != quantized.size:
        return False

    if source.mode != quantized.mode:
        try:
            quantized = quantized.convert(source.mode)
        except ValueError:
            return False

    return ImageChops.difference(source, quantized).getbbox() is None


def try_lossless(img: Image.Image, target_bytes: int):
    """
    Try strict lossless image optimization first.

    Returns:
        (
            best_bytes,
            best_fmt,
            method,
            extra,
            hit_target,
        )

    Strict lossless methods:
        - Verified PNG palette quantization
        - Optimized PNG
        - Lossless WebP

    Near-lossless WebP is attempted only when no strict
    lossless candidate meets the target size.
    """
    candidates = []

    # 1. Palette quantization

    colors = img.getcolors(maxcolors=256)

    if colors is not None:
        try:
            quantized = img.quantize(
                colors=256,
                method=Image.Quantize.FASTOCTREE,
                dither=Image.Dither.NONE,
            )

            # Only accept quantization if pixel data is identical.
            if _is_lossless_quantize(img, quantized):
                data = _encode(
                    quantized,
                    "PNG",
                    optimize=True,
                    compress_level=9,
                )

                candidates.append(
                    (
                        data,
                        "PNG",
                        "lossless",
                        {},
                    )
                )

        except (ValueError, OSError):
            # Quantization is an optimization candidate, not a
            # reason to fail the entire image optimization.
            pass

    # 2. Optimized PNG

    try:
        png_data = _encode(
            img,
            "PNG",
            optimize=True,
            compress_level=9,
        )

        candidates.append(
            (
                png_data,
                "PNG",
                "lossless",
                {},
            )
        )
    except (ValueError, OSError):
        pass

    # 3. Lossless WebP

    try:
        webp_data = _encode(
            img,
            "WEBP",
            lossless=True,
            method=6,
        )

        candidates.append(
            (
                webp_data,
                "WEBP",
                "lossless",
                {},
            )
        )
    except (ValueError, OSError):
        pass

    # No lossless candidate available

    if not candidates:
        raise ValueError("Unable to encode image using lossless formats")

    # Smallest lossless candidate.
    candidates.sort(key=lambda candidate: len(candidate[0]))
    best = candidates[0]

    # Target reached with strict lossless compression

    if len(best[0]) <= target_bytes:
        return (
            best[0],
            best[1],
            best[2],
            best[3],
            True,
        )

    # 4. Near-lossless WebP fallback

    for level in NEAR_LOSSLESS_LEVELS:
        try:
            data = _encode(
                img,
                "WEBP",
                near_lossless=level,
                method=6,
            )
        except (ValueError, OSError):
            continue

        candidate = (
            data,
            "WEBP",
            "near_lossless",
            {
                "near_lossless_level": level,
            },
        )

        # Return immediately when target is reached.
        if len(data) <= target_bytes:
            return (
                candidate[0],
                candidate[1],
                candidate[2],
                candidate[3],
                True,
            )

        # Otherwise keep the smallest candidate.
        if len(data) < len(best[0]):
            best = candidate

    # Target could not be reached
    return (
        best[0],
        best[1],
        best[2],
        best[3],
        False,
    )
