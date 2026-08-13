from django.urls import path

from .views import (
    UploadedImageListCreateAPIView,
    UploadedImageDetailAPIView,
)

urlpatterns = [
    path("images/", UploadedImageListCreateAPIView.as_view(), name="uploadedimage-list"),
    path("images/<int:pk>/", UploadedImageDetailAPIView.as_view(), name="uploadedimage-detail"),
]