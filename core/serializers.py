import os
import random
import requests
import urllib3

from datetime import datetime
from django.core.files.base import ContentFile
from djoser.serializers import UserSerializer as BaseUserSerializer, UserCreateSerializer as BaseUserCreateSerializer
from rest_framework import serializers
from .models import PoshUser, Campaign, Listing, ListingImage


class UserCreateSerializer(BaseUserCreateSerializer):
    class Meta(BaseUserCreateSerializer.Meta):
        fields = ['id', 'email', 'username', 'password', 'first_name', 'last_name']

        extra_kwargs = {
            'id': {'read_only': True},
        }


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
            'username': {'read_only': True},
            'first_name': {'read_only': True},
            'last_name': {'read_only': True},
            'phone_number': {'read_only': True},
            'profile_picture': {'read_only': True},
            'status': {'read_only': True},
            'sales': {'read_only': True},
            'profile_url': {'read_only': True}
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

        random_int = random.randint(100, 999)
        response = requests.get(f'https://poshmark.com/closet/{username}{random_int}')

        while response.status_code == requests.codes.ok:
            random_int = random.randint(100, 999)
            response = requests.get(f'https://poshmark.com/closet/{username}{random_int}')

        return f'{username}{random_int}'

    def get_new_posh_user(self):
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

        header_image_response = requests.get(header_image_url, timeout=10, headers=headers)

        profile_image_response = requests.get(profile_image_url, timeout=10, headers=headers)

        retries = 0
        
        while self.get_image_id(profile_image_response.url) in posh_user_info['picture_ids'] and retries < 10:
            profile_image_response = requests.get(profile_image_url, timeout=10, headers=headers)
            retries += 1

        while username in posh_user_info['usernames']:
            username = self.generate_username(first_name, last_name)

        new_user_info = {
            'first_name': first_name,
            'last_name': last_name,
            'gender': gender,
            'username': username if len(username) <= 12 else username[:12],
            'date_of_birth': date_of_birth,
            'profile_picture_url': profile_image_response.url,
            'header_picture_url': header_image_response.url,
            'profile_picture_id': self.get_image_id(profile_image_response.url),
        }

        return new_user_info

    def create(self, validated_data):
        user = self.context.get('user')
        all_data = {**validated_data, **self.get_new_posh_user()}
        picture_urls = {
            'profile_picture': all_data.pop('profile_picture_url'),
            'header_picture': all_data.pop('header_picture_url')
        }
        posh_user = PoshUser(**all_data)
        posh_user.user = user

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

            with open(file_name, 'rb') as img_temp:
                if key == 'profile_picture':
                    posh_user.profile_picture.save(file_name, ContentFile(img_temp.read()), save=True)
                else:
                    posh_user.header_picture.save(file_name, ContentFile(img_temp.read()), save=True)

            os.remove(file_name)

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
            'listing_price', 'lowest_price', 'images'
        ]

        extra_kwargs = {
            'id': {'read_only': True},
        }

    images = ListingImageSerializer(many=True, read_only=True)

    def create(self, validated_data):
        user = self.context.get('user')
        listing = Listing(**validated_data)
        listing.user = user
        listing.save()

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
