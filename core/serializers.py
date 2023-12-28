from django.core.files.base import ContentFile
from django.db.models import Q
from djoser.serializers import (
    UserSerializer as BaseUserSerializer,
    UserCreateSerializer as BaseUserCreateSerializer,
)
from rest_framework import serializers
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer as BaseTokenObtainPairSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from email_retrieval import zke_yahoo
from .models import (
    PoshUser,
    Campaign,
    Listing,
    ListingImage,
    ListedItem,
)


class TokenObtainPairSerializer(BaseTokenObtainPairSerializer):
    def validate(self, attrs):
        data = super(TokenObtainPairSerializer, self).validate(attrs)
        data["id"] = str(self.user.id)
        data["username"] = self.user.username

        return data


class UserCreateSerializer(BaseUserCreateSerializer):
    class Meta(BaseUserCreateSerializer.Meta):
        fields = ["id", "email", "username", "password", "first_name", "last_name"]

        extra_kwargs = {
            "id": {"read_only": True},
        }

    def to_representation(self, instance):
        data = super(UserCreateSerializer, self).to_representation(instance)
        user_tokens = RefreshToken.for_user(instance)
        tokens = {"access": str(user_tokens.access_token), "refresh": str(user_tokens)}
        data = {"success": "true", "data": {**data, **tokens}}
        return data


class UserSerializer(BaseUserSerializer):
    class Meta(BaseUserSerializer.Meta):
        fields = ["id", "email", "username", "first_name", "last_name"]

        extra_kwargs = {
            "id": {"read_only": True},
        }


class PoshUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = PoshUser
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "censored_email_password",
            "censored_email_imap_password",
            "censored_password",
            "phone_number",
            "profile_picture",
            "status",
            "profile_url",
            "sold_listings",
            "last_sale_time",
            "is_registered",
        ]
        extra_kwargs = {
            "id": {"read_only": True},
        }

    profile_url = serializers.SerializerMethodField(method_name="get_profile_url")
    censored_email_password = serializers.SerializerMethodField(
        method_name="get_email_password"
    )
    censored_email_imap_password = serializers.SerializerMethodField(
        method_name="get_email_imap_password"
    )
    censored_password = serializers.SerializerMethodField(method_name="get_password")

    @staticmethod
    def get_profile_url(posh_user: PoshUser):
        return f"https://poshmark.com/closet/{posh_user.username}"

    def get_password(self, posh_user: PoshUser):
        user = self.context.get("user")
        if (
            user.username == "david" and posh_user.is_registered
        ) or ListedItem.objects.filter(
            Q(posh_user=posh_user, datetime_sold__isnull=False)
            | Q(posh_user=posh_user, datetime_redeemable__isnull=False)
        ).exists():
            return posh_user.password
        return "***********"

    def get_email_imap_password(self, posh_user: PoshUser):
        user = self.context.get("user")
        if (
            user.username == "david" and posh_user.is_registered
        ) or ListedItem.objects.filter(
            Q(posh_user=posh_user, datetime_sold__isnull=False)
            | Q(posh_user=posh_user, datetime_redeemable__isnull=False)
        ).exists():
            return posh_user.email_imap_password
        return "***********"

    def get_email_password(self, posh_user: PoshUser):
        user = self.context.get("user")
        if (
            user.username == "david" and posh_user.is_registered
        ) or ListedItem.objects.filter(
            Q(posh_user=posh_user, datetime_sold__isnull=False)
            | Q(posh_user=posh_user, datetime_redeemable__isnull=False)
        ).exists():
            return posh_user.email_password
        return "***********"

    def create(self, validated_data):
        used_full_names = self.context.get("used_full_names")
        used_profile_picture_ids = self.context.get("used_profile_picture_ids")
        faker_obj = self.context.get("faker_obj")
        user = self.context.get("user")
        path = self.context.get("path")
        if "generate" in path:
            email = validated_data.get("email")
            email_password = validated_data.get("email_password", "")
            email_imap_password = validated_data.get("email_imap_password", "")
            email_id = validated_data.get("email_id", None)

            try:
                posh_user = PoshUser.generate(
                    faker_obj,
                    user,
                    email,
                    email_password=email_password,
                    email_imap_password=email_imap_password,
                    email_id=email_id,
                    excluded_names=used_full_names,
                    excluded_profile_picture_ids=used_profile_picture_ids,
                )

                if email_id:
                    zke_yahoo.update_email_status([email_id], "used")
            except Exception as e:
                if email_id:
                    zke_yahoo.update_email_status([email_id], "free")
                raise e

        else:
            posh_user = PoshUser(**validated_data)

            posh_user.is_registered = True
            posh_user.user = user
            posh_user.save()

        return posh_user


class ListingImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingImage
        fields = ["id", "image"]

    def create(self, validated_data):
        listing_id = self.context.get("listing_pk")
        listing_image = ListingImage(**validated_data)
        listing_image.listing = Listing.objects.get(id=listing_id)

        listing_image.save()

        return listing_image


class ListingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Listing
        fields = [
            "id",
            "title",
            "size",
            "brand",
            "category",
            "subcategory",
            "cover_photo",
            "description",
            "original_price",
            "listing_price",
            "lowest_price",
            "images",
            "assigned",
        ]

        extra_kwargs = {
            "id": {"read_only": True},
        }

    images = ListingImageSerializer(many=True, read_only=True)
    assigned = serializers.SerializerMethodField(method_name="check_assigned")

    @staticmethod
    def check_assigned(listing: PoshUser):
        return True if listing.campaign else False

    def create(self, validated_data):
        files = self.context.get("files")
        user = self.context.get("user")
        listing = Listing(**validated_data)
        listing.user = user
        listing.save()

        for name, file in files.items():
            if name != "cover_photo":
                listing_image = ListingImage(
                    listing=listing,
                )
                listing_image.image.save(name, ContentFile(file.read()), save=True)

        return listing


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "id",
            "auto_run",
            "generate_users",
            "title",
            "mode",
            "delay",
            "status",
            "posh_user",
            "listings",
            "queue_status",
        ]
        extra_kwargs = {"id": {"read_only": True}, "status": {"read_only": True}}

    def create(self, validated_data):
        listings = validated_data.pop("listings")
        user = self.context.get("user")
        campaign = Campaign(**validated_data)
        campaign.user = user
        campaign.save()

        for listing in listings:
            campaign.listings.add(listing)

        return campaign
