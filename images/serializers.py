from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import ImageUpload, ImageVariant
from .validators import (
    validate_upload_size,
    detect_format,
    is_animated,
    get_dimensions,
    validate_min_dimensions,
)
from .services.optimizer import compress_image
from .services.variations import generate_variants


def human_readable_size(num_bytes: int) -> str:
    if num_bytes is None:
        return None
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    return f"{num_bytes / 1024:.2f} KB"

class ImageVariantSerializer(serializers.ModelSerializer):
    file_size_display = serializers.SerializerMethodField()

    class Meta:
        model = ImageVariant
        fields = [
            "variant_type",
            "image",
            "width",
            "height",
            "format",
            "file_size",
            "file_size_display",
        ]

    def get_file_size_display(self, obj):
        return human_readable_size(obj.file_size)


class ImageUploadSerializer(serializers.ModelSerializer):
    # Input-only fields — not persisted directly, consumed in validate()/create()
    image_file = serializers.FileField(write_only=True)
    image_type = serializers.ChoiceField(
        choices=ImageUpload.ImageType.choices, write_only=True
    )

    # Human-readable, response-only — DB always stores raw bytes for precision
    original_size_display = serializers.SerializerMethodField()
    optimized_size_display = serializers.SerializerMethodField()
    target_size_display = serializers.SerializerMethodField()

    compression_ratio = serializers.FloatField(read_only=True)
    variants = ImageVariantSerializer(many=True, read_only=True)

    class Meta:
        model = ImageUpload
        fields = [
            "id",
            "image_file",
            "image_type",
            "image",
            "original_filename",
            "original_format",
            "optimized_format",
            "original_size",
            "original_size_display",
            "optimized_size",
            "optimized_size_display",
            "target_size",
            "target_size_display",
            "original_width",
            "original_height",
            "optimized_width",
            "optimized_height",
            "method",
            "quality",
            "near_lossless_level",
            "scale",
            "compression_ratio",
            "variants",
            "created_at",
        ]
        read_only_fields = [f for f in fields if f not in ("image_file", "image_type")]

    def get_original_size_display(self, obj):
        return human_readable_size(obj.original_size)

    def get_optimized_size_display(self, obj):
        return human_readable_size(obj.optimized_size)

    def get_target_size_display(self, obj):
        return human_readable_size(obj.target_size)

    def validate(self, attrs):
        file = attrs["image_file"]
        image_type = attrs["image_type"]

        try:
            validate_upload_size(file)
            fmt = detect_format(file)
            animated = is_animated(file, fmt)
            width, height = get_dimensions(file, fmt)
            validate_min_dimensions(width, height, image_type)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(str(exc))

        # Stash for create() — avoids re-detecting format/animation a second time
        attrs["_fmt"] = fmt
        attrs["_animated"] = animated
        return attrs

    def create(self, validated_data):
        file = validated_data["image_file"]
        image_type = validated_data["image_type"]
        fmt = validated_data["_fmt"]
        animated = validated_data["_animated"]

        result = compress_image(file, image_type, fmt, animated)

        instance = ImageUpload(
            image_type=image_type,
            original_filename=file.name,
            original_format=fmt,
            original_size=result.original_size,
            optimized_format=result.format,
            optimized_size=result.optimized_size,
            target_size=result.target_size,
            original_width=result.original_width,
            original_height=result.original_height,
            optimized_width=result.optimized_width,
            optimized_height=result.optimized_height,
            method=result.method,
            quality=result.quality,
            near_lossless_level=result.near_lossless_level,
            scale=result.scale,
        )
        
        # Save instance FIRST to assign DB ID
        instance.save()
          
        instance.image.save(result.filename, ContentFile(result.data), save=False)
        
        # Save variants using parent ID
        variant_objs = []
        for v in generate_variants(result, image_type):
            variant = ImageVariant(
                image_upload=instance,
                variant_type=v["variant_type"],
                width=v["width"],
                height=v["height"],
                format=v["format"],
                file_size=v["file_size"],
            )
            variant.image.save(v["filename"], ContentFile(v["data"]), save=False)
            variant_objs.append(variant)

        if variant_objs:
            ImageVariant.objects.bulk_create(variant_objs)

        return instance
