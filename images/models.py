from django.db import models
from django.core.validators import FileExtensionValidator

import os


def upload_to_original(instance, filename):
    return f"uploads/originals/{instance.id}_{filename}"


def upload_to_variant(instance, filename):
    # Uses parent ImageUpload ID
    return f"uploads/variants/{instance.image_upload_id}_{filename}"

class ImageUpload(models.Model):
    class ImageType(models.TextChoices):
        REGULAR = "regular", "Regular"
        HERO = "hero", "Hero"
        THUMBNAIL = "thumbnail", "Thumbnail"
        LOGO = "logo", "Logo"

    class Method(models.TextChoices):
        LOSSLESS = "lossless", "Lossless"
        NEAR_LOSSLESS = "near_lossless", "Near Lossless"
        LOSSY = "lossy", "Lossy"
        LOSSY_RESIZED = "lossy_resized", "Lossy + Resized"
        FORCED_FIT = "forced_fit", "Forced Fit"
        SKIPPED = "skipped", "Skipped (GIF/SVG/animated)"
        NOT_NEEDED = "not_needed", "Already Under Target"

    image_type = models.CharField(max_length=20, choices=ImageType.choices)

    image = models.FileField(upload_to=upload_to_original)

    original_filename = models.CharField(max_length=255)
    original_format = models.CharField(max_length=10)
    optimized_format = models.CharField(max_length=10)

    original_size = models.PositiveIntegerField(help_text="bytes")
    optimized_size = models.PositiveIntegerField(help_text="bytes")
    target_size = models.PositiveIntegerField(help_text="bytes")

    original_width = models.PositiveIntegerField(null=True, blank=True)
    original_height = models.PositiveIntegerField(null=True, blank=True)
    optimized_width = models.PositiveIntegerField(null=True, blank=True)
    optimized_height = models.PositiveIntegerField(null=True, blank=True)

    method = models.CharField(max_length=20, choices=Method.choices)
    quality = models.PositiveIntegerField(null=True, blank=True)
    near_lossless_level = models.PositiveIntegerField(null=True, blank=True)
    scale = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def compression_ratio(self):
        if self.original_size == 0:
            return 0.0
        return round(1 - (self.optimized_size / self.original_size), 4)

    def __str__(self):
        return f"{self.original_filename} ({self.image_type}, {self.method})"


class ImageVariant(models.Model):
    class VariantType(models.TextChoices):
        MOBILE = "mobile", "Mobile"
        LAPTOP = "laptop", "Laptop"
        DESKTOP = "desktop", "Desktop"

    image_upload = models.ForeignKey(
        ImageUpload,
        on_delete=models.CASCADE,
        related_name="variants",
    )

    variant_type = models.CharField(
        max_length=10,
        choices=VariantType.choices,
    )

    image = models.FileField(upload_to=upload_to_variant)

    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()

    format = models.CharField(max_length=10)
    file_size = models.PositiveIntegerField(help_text="bytes")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["image_upload", "variant_type"],
                name="unique_image_upload_variant_type",
            ),
        ]
        ordering = ["width"]

    def __str__(self):
        return (
            f"{self.image_upload.original_filename} "
            f"({self.variant_type}, {self.width}x{self.height})"
        )
