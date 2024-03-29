import datetime

import pytz
from django.db.models import Value
from django.db.models.functions import Concat
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from faker import Faker
from rest_framework import filters
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import (
    RetrieveModelMixin,
    ListModelMixin,
    CreateModelMixin,
    UpdateModelMixin,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.views import (
    TokenObtainPairView as BaseTokenObtainPairView,
)

from email_retrieval import zke_yahoo
from . import serializers
from .mixins import DestroyWithPayloadModelMixin
from .models import PoshUser, Campaign, Listing, ListingImage, ListedItem


class TokenObtainPairView(BaseTokenObtainPairView):
    serializer_class = serializers.TokenObtainPairSerializer


class PoshUserViewSet(
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyWithPayloadModelMixin,
    ListModelMixin,
    GenericViewSet,
):
    serializer_class = serializers.PoshUserSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    search_fields = ["email", "username"]
    filterset_fields = ["user_id"]

    def get_queryset(self):
        user = self.request.user
        unassinged = self.request.query_params.get("unassigned")

        queryset = PoshUser.objects.filter(user=user, is_active=True).prefetch_related(
            "campaign"
        )

        if unassinged == "true":
            queryset = queryset.filter(campaign__isnull=True)

        return queryset

    def get_serializer_context(self):
        context = super(PoshUserViewSet, self).get_serializer_context()
        new_context = {"user": self.request.user, "path": self.request.path}

        if self.action == "generate":
            fake = Faker()

            # Retrieve the 'full_name' property from all PoshUser objects
            full_names = PoshUser.objects.annotate(
                full_name=Concat("first_name", Value(" "), "last_name")
            ).values_list("full_name", flat=True)
            profile_picture_ids = PoshUser.objects.values_list(
                "profile_picture_id", flat=True
            )

            # Convert the QuerySet to a list
            full_names_list = list(full_names)
            profile_picture_ids_list = list(profile_picture_ids)

            new_context["used_full_names"] = full_names_list
            new_context["used_profile_picture_ids"] = profile_picture_ids_list
            new_context["faker_obj"] = fake

        context.update(new_context)

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

    @action(detail=False, methods=["POST"])
    def generate(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        if not serializer.validated_data[0].get("email"):
            # Get the number of valid PoshUser instances
            num_valid_users = len(serializer.validated_data)

            count = zke_yahoo.check_availability()
            if count < num_valid_users:
                return Response(
                    {"error": f"Only {count} emails are available"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            email_ids = []
            emails = zke_yahoo.get_emails(count)

            for index, data in enumerate(serializer.validated_data):
                email_ids.append(emails[index][0])
                data["email_id"] = emails[index][0]
                data["email"] = emails[index][1]
                data["email_password"] = emails[index][2]
                data["email_imap_password"] = emails[index][3]

            zke_yahoo.update_email_status(email_ids, "on_hold")

        self.perform_create(serializer)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["POST"])
    def disable(self, request, pk):
        posh_user = self.get_object()

        try:
            update_fields = ["posh_user"]
            campaign = Campaign.objects.get(user=self.request.user, posh_user=posh_user)

            if campaign.status not in (Campaign.STOPPED, Campaign.STOPPING):
                update_fields.append("status")
                campaign.status = Campaign.STOPPING
            campaign.posh_user = None
            campaign.save(update_fields=update_fields)
        except Campaign.DoesNotExist:
            pass

        posh_user.is_active = False
        posh_user.save(update_fields=["is_active"])

        serializer = self.get_serializer(posh_user)

        return Response(serializer.data)


class ListingViewSet(
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyWithPayloadModelMixin,
    ListModelMixin,
    GenericViewSet,
):
    serializer_class = serializers.ListingSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    search_fields = ["title"]
    filterset_fields = ["user_id"]

    def get_queryset(self):
        queryset = Listing.objects.filter(user=self.request.user)

        return queryset

    def get_serializer_context(self):
        context = super(ListingViewSet, self).get_serializer_context()
        context.update({"user": self.request.user})
        context.update({"files": self.request.FILES})

        return context

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data

        try:
            campaign = Campaign.objects.get(listings__exact=instance)
        except Campaign.DoesNotExist:
            campaign = None

        if campaign and campaign.status != Campaign.STOPPED:
            return Response(data, status.HTTP_400_BAD_REQUEST)

        self.perform_destroy(instance)

        return Response(data, status=status.HTTP_200_OK)


class ListingImageViewSet(
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyWithPayloadModelMixin,
    ListModelMixin,
    GenericViewSet,
):
    serializer_class = serializers.ListingImageSerializer

    def get_queryset(self):
        queryset = ListingImage.objects.filter(listing_id=self.kwargs["listing_pk"])

        return queryset

    def get_serializer_context(self):
        context = super(ListingImageViewSet, self).get_serializer_context()
        context.update({"listing_pk": self.kwargs["listing_pk"]})

        return context


class CampaignViewSet(
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyWithPayloadModelMixin,
    ListModelMixin,
    GenericViewSet,
):
    serializer_class = serializers.CampaignSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    search_fields = ["title"]
    filterset_fields = ["user_id"]

    def get_queryset(self):
        queryset = Campaign.objects.filter(user=self.request.user)

        return queryset

    def get_serializer_context(self):
        context = super(CampaignViewSet, self).get_serializer_context()
        context.update({"user": self.request.user})
        return context

    @action(detail=True, methods=["POST"])
    def start(self, request, pk):
        campaign = self.get_object()
        serializer = self.get_serializer(campaign)

        if campaign.posh_user and campaign.posh_user.is_active_in_posh:
            campaign.status = Campaign.STARTING
            campaign.next_runtime = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
            campaign.queue_status = "CALCULATING"
            campaign.save(update_fields=["status", "next_runtime", "queue_status"])

        return Response(serializer.data)

    @action(detail=True, methods=["POST"])
    def stop(self, request, pk):
        campaign = self.get_object()
        campaign.status = Campaign.STOPPING
        campaign.next_runtime = None
        campaign.save(update_fields=["status", "next_runtime"])

        serializer = self.get_serializer(campaign)

        return Response(serializer.data)
