from rest_framework import status
from rest_framework.response import Response


class DestroyWithPayloadModelMixin:
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        self.perform_destroy(instance)

        return Response(data, status=status.HTTP_200_OK)

    def perform_destroy(self, instance):
        instance.delete()
