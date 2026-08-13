from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from .models import ImageUpload
from .serializers import ImageUploadSerializer


class UploadedImageListCreateAPIView(APIView):

    def get(self, request):
        queryset = ImageUpload.objects.all()
        serializer = ImageUploadSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = ImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        response_serializer = ImageUploadSerializer(instance)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class UploadedImageDetailAPIView(APIView):
    def get(self, request, pk):
        obj = get_object_or_404(ImageUpload, pk=pk)
        serializer = ImageUploadSerializer(obj)
        return Response(serializer.data)

    def delete(self, request, pk):
        obj = get_object_or_404(ImageUpload, pk=pk)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)