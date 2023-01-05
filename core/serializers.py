import os
import random
import requests
import urllib3

from datetime import datetime
from django.core.files.base import ContentFile
from djoser.serializers import UserSerializer as BaseUserSerializer, UserCreateSerializer as BaseUserCreateSerializer
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer as BaseTokenObtainPairSerializer
from .models import PoshUser, Campaign, Listing, ListingImage, LogEntry, LogGroup


class TokenObtainPairSerializer(BaseTokenObtainPairSerializer):
    def validate(self, attrs):
        data = super(TokenObtainPairSerializer, self).validate(attrs)
        data['id'] = str(self.user.id)
        data['username'] = self.user.username

        return data


class UserCreateSerializer(BaseUserCreateSerializer):
    class Meta(BaseUserCreateSerializer.Meta):
        fields = ['id', 'email', 'username', 'password', 'first_name', 'last_name']

        extra_kwargs = {
            'id': {'read_only': True},
        }

    def to_representation(self, instance):
        data = super(UserCreateSerializer, self).to_representation(instance)
        user_tokens = RefreshToken.for_user(instance)
        tokens = {'access': str(user_tokens.access_token), 'refresh': str(user_tokens)}
        data = {
            "success": "true",
            "data": {**data, **tokens}
        }
        return data


class UserSerializer(BaseUserSerializer):
    class Meta(BaseUserSerializer.Meta):
        fields = ['id', 'email', 'username', 'first_name', 'last_name']

        extra_kwargs = {
            'id': {'read_only': True},
        }


class PoshUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = PoshUser
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'password', 'phone_number', 'profile_picture',
            'status', 'sales', 'profile_url'
        ]
        extra_kwargs = {
            'id': {'read_only': True},
        }

    profile_url = serializers.SerializerMethodField(method_name='get_profile_url')

    @staticmethod
    def get_profile_url(posh_user: PoshUser):
        return f'https://poshmark.com/closet/{posh_user.username}'

    @staticmethod
    def get_image_id(url):
        return url[url.rfind('/') + 1:url.find('?')]

    @staticmethod
    def generate_username(first_name, last_name):
        username = f'{first_name.lower()}_{last_name.lower()}'
        username_length = len(username)

        if username_length > 12:
            username = username[:(12 - username_length)]

        response = requests.get(f'https://poshmark.com/closet/{username}')

        while response.status_code == requests.codes.ok:
            random_int = random.randint(100, 999)
            username = f'{username[:-3]}{random_int}'
            response = requests.get(f'https://poshmark.com/closet/{username}')

        return username

    def get_new_posh_user(self, email=None):
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; CrOS x86_64 12871.102.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.141 Safari/537.36'
        }

        user_payload = {
            'nat': 'US',
            'password': 'upper,lower,number,10-12',
            'inc': 'gender,nat,name,email,login,dob,picture,password',
            'results': 1
        }
        user_url = 'https://randomuser.me/api/'
        header_image_url = 'https://picsum.photos/1920/300'
        all_posh_users = PoshUser.objects.all()
        posh_user_info = {
            'picture_ids': [],
            'usernames': []
        }

        for posh_user in all_posh_users:
            posh_user_info['picture_ids'].append(posh_user.profile_picture_id)
            posh_user_info['usernames'].append(posh_user.username)

        user_response = requests.get(user_url, params=user_payload, timeout=10, headers=headers)
        user_info = user_response.json()['results'][0]
        first_name = user_info['name']['first']
        last_name = user_info['name']['last']
        gender = user_info['gender'][0].upper()
        username = self.generate_username(first_name, last_name)
        profile_image_url = f'https://source.unsplash.com/600x600/?{user_info["gender"]}'
        date_of_birth = datetime.strptime(user_info['dob']['date'][:-5], '%Y-%m-%dT%H:%M:%S')
        email_id = ''

        header_image_response = requests.get(header_image_url, timeout=10, headers=headers)

        profile_image_response = requests.get(profile_image_url, timeout=10, headers=headers)

        retries = 0

        while self.get_image_id(profile_image_response.url) in posh_user_info['picture_ids'] and retries < 10:
            profile_image_response = requests.get(profile_image_url, timeout=10, headers=headers)
            retries += 1

        while username in posh_user_info['usernames']:
            username = self.generate_username(first_name, last_name)


        if not email:
            # user = self.context.get('user')
            email_id, email = PoshUser.create_email(first_name, last_name)

        new_user_info = {
            'first_name': first_name,
            'last_name': last_name,
            'gender': gender,
            'username': username if len(username) <= 12 else username[:12],
            'email_id': email_id,
            'email': email,
            'date_of_birth': date_of_birth,
            'profile_picture_url': profile_image_response.url,
            'header_picture_url': header_image_response.url,
            'profile_picture_id': self.get_image_id(profile_image_response.url),
        }

        return new_user_info

    def create(self, validated_data):
        user = self.context.get('user')
        path = self.context.get('path')
        if 'generate' in path:
            email = None
            try:
                email = validated_data.pop('email')
            except KeyError:
                pass
            all_data = {**validated_data, **self.get_new_posh_user(email)}

            picture_urls = {
                'profile_picture': all_data.pop('profile_picture_url'),
                'header_picture': all_data.pop('header_picture_url')
            }
            posh_user = PoshUser(**all_data)

            for key, value in picture_urls.items():
                file_name = f'{posh_user.username}.png'

                http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=5))
                response = http.request('GET', value, preload_content=False)
                with open(file_name, 'wb') as img_temp:
                    while True:
                        data = response.read(65536)
                        if not data:
                            break
                        img_temp.write(data)

                response.release_conn()
                posh_user.user = user
                posh_user.save()

                with open(file_name, 'rb') as img_temp:
                    if key == 'profile_picture':
                        posh_user.profile_picture.save(f'profile_{file_name}', ContentFile(img_temp.read()), save=False)
                    else:
                        posh_user.header_picture.save(f'header_{file_name}', ContentFile(img_temp.read()), save=False)

                os.remove(file_name)

                posh_user.save()

        else:
            posh_user = PoshUser(**validated_data)
            
            posh_user.is_registered = True
            posh_user.user = user
            posh_user.save()

        return posh_user


class ListingImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingImage
        fields = ['id', 'image']

    def create(self, validated_data):
        listing_id = self.context.get('listing_pk')
        listing_image = ListingImage(**validated_data)
        listing_image.listing = Listing.objects.get(id=listing_id)

        listing_image.save()

        return listing_image


class ListingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Listing
        fields = [
            'id', 'title', 'size', 'brand', 'category', 'subcategory', 'cover_photo', 'description', 'original_price',
            'listing_price', 'lowest_price', 'images', 'assigned'
        ]

        extra_kwargs = {
            'id': {'read_only': True},
        }

    images = ListingImageSerializer(many=True, read_only=True)
    assigned = serializers.SerializerMethodField(method_name='check_assigned')

    @staticmethod
    def check_assigned(listing: PoshUser):
        return True if listing.campaign else False

    def create(self, validated_data):
        files = self.context.get('files')
        user = self.context.get('user')
        listing = Listing(**validated_data)
        listing.user = user
        listing.save()

        for name, file in files.items():
            print(name, file)
            if name != 'cover_photo':
                listing_image = ListingImage(
                    listing=listing,
                )
                listing_image.image.save(name, ContentFile(file.read()), save=True)

        return listing


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            'id', 'auto_run', 'generate_users', 'title', 'mode', 'delay', 'status',  'posh_user', 'listings']
        extra_kwargs = {
            'id': {'read_only': True},
            'status': {'read_only': True}
        }

    def create(self, validated_data):
        listings = validated_data.pop('listings')
        user = self.context.get('user')
        campaign = Campaign(**validated_data)
        campaign.user = user
        campaign.save()

        for listing in listings:
            campaign.listings.add(listing)

        return campaign


class LogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LogEntry
        fields = ['id', 'log_level', 'log_group', 'timestamp', 'message', 'image']

        extra_kwargs = {
            'id': {'read_only': True},
        }

    log_level = serializers.SerializerMethodField(method_name='get_log_level')

    @staticmethod
    def get_log_level(log_entry: LogEntry):
        if log_entry.level >= LogEntry.CRITICAL:
            return 'CRITICAL'
        elif log_entry.level >= LogEntry.ERROR:
            return 'ERROR'
        elif log_entry.level >= LogEntry.WARNING:
            return 'WARNING'
        elif log_entry.level >= LogEntry.INFO:
            return 'INFO'
        elif log_entry.level >= LogEntry.DEBUG:
            return 'DEBUG'
        else:
            return 'NOTSET'


class LogGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogGroup
        fields = ['id', 'campaign', 'posh_user', 'created_date', 'log_entries']

        extra_kwargs = {
            'id': {'read_only': True},
            'created_date': {'read_only': True},
        }

    log_entries = LogEntrySerializer(many=True, read_only=True)
