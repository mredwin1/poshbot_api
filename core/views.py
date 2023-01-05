import logging

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import RetrieveModelMixin, ListModelMixin, CreateModelMixin, UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.views import TokenObtainPairView as BaseTokenObtainPairView
from .mixins import DestroyWithPayloadModelMixin
from .models import PoshUser, Campaign, Listing, ListingImage, LogGroup
from .tasks import init_campaign, basic_sharing_campaign, advanced_sharing_campaign
from . import serializers


logger = logging.getLogger(__name__)


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
        unassinged = self.request.query_params.get('unassigned')

        queryset = PoshUser.objects.filter(user=user).prefetch_related('campaign')

        if unassinged == 'true':
            queryset = queryset.filter(campaign__isnull=True)

        return queryset

    def get_serializer_context(self):
        context = super(PoshUserViewSet, self).get_serializer_context()
        context.update({'user': self.request.user, 'path': self.request.path})

        return context

    @action(detail=False, methods=['POST'])
    def generate(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


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
        context.update({'files': self.request.FILES})

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
        campaign = self.get_object()
        serializer = self.get_serializer(campaign)

        if campaign.mode == Campaign.ADVANCED_SHARING and campaign.posh_user and not campaign.posh_user.is_registered:
            advanced_sharing = init_campaign
        else:
            advanced_sharing = advanced_sharing_campaign

        campaign_mapping = {
            Campaign.BASIC_SHARING: basic_sharing_campaign,
            Campaign.ADVANCED_SHARING: advanced_sharing
        }

        if campaign.posh_user:
            logger = LogGroup(campaign=campaign, posh_user=campaign.posh_user)
            logger.save()
            campaign.status = Campaign.IDLE
            campaign.save()

            campaign_mapping[campaign.mode].delay(pk, logger.id)

        return Response(serializer.data)

    @action(detail=True, methods=['POST'])
    def stop(self, request, pk):
        campaign = self.get_object()
        campaign.status = Campaign.STOPPED
        campaign.save()
        serializer = self.get_serializer(campaign)

        return Response(serializer.data)


class LogGroupViewSet(RetrieveModelMixin, ListModelMixin, GenericViewSet):
    serializer_class = serializers.LogGroupSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LogGroup.objects.filter(campaign_id=self.kwargs['campaign_pk'])

        return queryset
