from django.db import models
from django.core.validators import FileExtensionValidator


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

    image = models.FileField(upload_to='uploads/%Y/%m/%d/')

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
