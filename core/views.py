import datetime
import pytz

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
from .models import PoshUser, Campaign, Listing, ListingImage, LogGroup, ListedItem
from .tasks import CampaignTask
from . import serializers


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

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data

        try:
            campaign = Campaign.objects.get(posh_user=instance)
        except Campaign.DoesNotExist:
            campaign = None

        if campaign and campaign.status != Campaign.STOPPED:
            return Response(data, status.HTTP_400_BAD_REQUEST)

        self.perform_destroy(instance)

        return Response(data, status=status.HTTP_200_OK)

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

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data

        try:
            campaign = Campaign.objects.get(listings__contains=instance)
        except Campaign.DoesNotExist:
            campaign = None

        if campaign and campaign.status != Campaign.STOPPED:
            return Response(data, status.HTTP_400_BAD_REQUEST)

        self.perform_destroy(instance)

        return Response(data, status=status.HTTP_200_OK)


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

        if campaign.posh_user and campaign.posh_user.is_active_in_posh:
            campaign_listings = Listing.objects.filter(campaign__id=campaign.id)
            items_to_list = []

            for campaign_listing in campaign_listings:
                try:
                    listed_item = ListedItem.objects.get(posh_user=campaign.posh_user, listing=campaign_listing)
                    if listed_item.status == ListedItem.NOT_LISTED:
                        items_to_list.append(campaign_listing)

                except ListedItem.DoesNotExist:
                    item_to_list = ListedItem(posh_user=campaign.posh_user, listing=campaign_listing, listing_title=campaign_listing.title)
                    item_to_list.save()
                    items_to_list.append(item_to_list)

            campaign.status = Campaign.STARTING
            campaign.next_runtime = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
            campaign.queue_status = 'CALCULATING'
            campaign.save()

        return Response(serializer.data)

    @action(detail=True, methods=['POST'])
    def stop(self, request, pk):
        campaign = self.get_object()
        campaign.status = Campaign.STOPPING
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
