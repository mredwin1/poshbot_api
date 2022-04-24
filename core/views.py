from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.mixins import RetrieveModelMixin, ListModelMixin, CreateModelMixin, UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView
from .mixins import DestroyWithPayloadModelMixin
from .models import PoshUser, Campaign, Listing, ListingImage
from .tasks import advanced_sharing_campaign
from . import serializers as serializers


class TokenObtainPairView(BaseTokenObtainPairView):
    serializer_class = serializers.TokenObtainPairSerializer


class PoshUserViewSet(RetrieveModelMixin, DestroyWithPayloadModelMixin, ListModelMixin, CreateModelMixin, GenericViewSet):
    serializer_class = serializers.PoshUserSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    search_fields = ['email', 'username']
    filterset_fields = ['user_id']

    def get_queryset(self):
        user = self.request.user
        queryset = PoshUser.objects.filter(user=user).prefetch_related('campaign')

        return queryset

    def get_serializer_context(self):
        context = super(PoshUserViewSet, self).get_serializer_context()
        context.update({'user': self.request.user})
        return context


class ListingViewSet(CreateModelMixin, RetrieveModelMixin, UpdateModelMixin, DestroyWithPayloadModelMixin, ListModelMixin, GenericViewSet):
    serializer_class = serializers.ListingSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    search_fields = ['title']
    filterset_fields = ['user_id']

    def get_queryset(self):
        queryset = Listing.objects.filter(user=self.request.user)

        return queryset

    def get_serializer_context(self):
        context = super(ListingViewSet, self).get_serializer_context()
        context.update({'user': self.request.user})

        return context


class ListingImageViewSet(CreateModelMixin, RetrieveModelMixin, UpdateModelMixin, DestroyWithPayloadModelMixin, ListModelMixin, GenericViewSet):
    serializer_class = serializers.ListingImageSerializer

    def get_queryset(self):
        queryset = ListingImage.objects.filter(listing_id=self.kwargs['listing_pk'])

        return queryset

    def get_serializer_context(self):
        context = super(ListingImageViewSet, self).get_serializer_context()
        context.update({'listing_pk': self.kwargs['listing_pk']})

        return context


class CampaignViewSet(CreateModelMixin, RetrieveModelMixin, UpdateModelMixin, DestroyWithPayloadModelMixin, ListModelMixin, GenericViewSet):
    serializer_class = serializers.CampaignSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    search_fields = ['title']
    filterset_fields = ['user_id']

    def get_queryset(self):
        queryset = Campaign.objects.filter(user=self.request.user)

        return queryset

    def get_serializer_context(self):
        context = super(CampaignViewSet, self).get_serializer_context()
        context.update({'user': self.request.user})
        return context

    @action(detail=True, methods=['POST'])
    def start(self, request, pk):
        advanced_sharing_campaign.delay(pk)

        return Response({'status': 'started'})

    @action(detail=True, methods=['POST'])
    def stop(self, request, pk):
        campaign = self.get_object()
        campaign.status = Campaign.STOPPED
        campaign.save()

        return Response({'status': 'stopped'})