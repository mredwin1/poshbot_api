import boto3
import os
import random
import requests
import string

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFill, Transpose
from uuid import uuid4


def path_and_rename(instance, filename):
    upload_to = 'listing_images'
    ext = filename.split('.')[-1]

    if isinstance(instance, Listing):
        path = instance.title.replace(' ', '_')
        filename = f'cover_photo.{ext}'

    else:
        aws_session = boto3.Session()
        s3_client = aws_session.resource('s3', aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
                                         aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
                                         region_name=settings.AWS_S3_REGION_NAME)

        path = instance.listing.title.replace(' ', '_')
        filename = None

        while not filename:
            rand_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            filename = f'image_{rand_str}.{ext}'
            try:
                s3_client.Object(settings.AWS_STORAGE_BUCKET_NAME, os.path.join(upload_to, path, 'images', filename)).load()
                filename = None
            except Exception:
                pass

    return os.path.join(upload_to, path, 'images', filename)


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.username


class PoshUser(models.Model):
    MALE = 'M'
    FEMALE = 'F'

    GENDER_CHOICES = [
        (MALE, 'Male'),
        (FEMALE, 'Female')
    ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    username = models.CharField(max_length=15, unique=True, blank=True)
    password = models.CharField(max_length=20,
                                help_text='Must be at least 6 characters and must contain a number or symbol.')
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    gender = models.CharField(max_length=2, choices=GENDER_CHOICES, blank=True)
    phone_number = models.CharField(max_length=20, default='', blank=True)
    profile_picture_id = models.CharField(max_length=200, blank=True)

    profile_picture = models.ImageField(upload_to='profile_pictures', null=True, blank=True)
    header_picture = models.ImageField(upload_to='header_pictures', null=True, blank=True)

    email = models.EmailField(blank=True)

    sales = models.PositiveSmallIntegerField(default=0, blank=True)

    date_added = models.DateField(auto_now_add=True)
    date_of_birth = models.DateField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_registered = models.BooleanField(default=False)
    profile_updated = models.BooleanField(default=False)

    @property
    def status(self):
        if not self.is_active:
            return 'Inactive'

        assigned_campaign = Campaign.objects.filter(posh_user=self)

        if not assigned_campaign:
            return 'Unassigned'
        elif self.campaign and self.campaign.status == Campaign.RUNNING:
            return 'Running'
        elif self.campaign:
            return 'Assigned'

    def __str__(self):
        return self.username

    class Meta:
        ordering = ['username']


class Campaign(models.Model):
    RUNNING = '1'
    IDLE = '2'
    STOPPED = '3'

    STATUS_CHOICES = [
        (RUNNING, 'RUNNING'),
        (IDLE, 'IDLE'),
        (STOPPED, 'STOPPED'),
    ]

    ADVANCED_SHARING = '0'
    BASIC_SHARING = '1'

    MODE_CHOICES = [
        (ADVANCED_SHARING, 'Advanced Sharing'),
        (BASIC_SHARING, 'Basic Sharing'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    posh_user = models.OneToOneField(PoshUser, on_delete=models.SET_NULL, blank=True, null=True)

    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='0')
    title = models.CharField(max_length=30)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STOPPED)

    delay = models.SmallIntegerField()
    lowest_price = models.SmallIntegerField(default=250)

    auto_run = models.BooleanField(default=True)
    generate_users = models.BooleanField(default=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['title']


class Listing(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    title = models.CharField(max_length=50)
    size = models.CharField(max_length=20)
    brand = models.CharField(max_length=30)
    category = models.CharField(max_length=30)
    subcategory = models.CharField(max_length=30)

    cover_photo = ProcessedImageField(
        processors=[
            Transpose(),
            ResizeToFill(1000, 1000)
        ],
        format='PNG',
        options={'quality': 60},
        upload_to=path_and_rename
    )
    description = models.TextField()

    original_price = models.IntegerField()
    listing_price = models.IntegerField()
    lowest_price = models.IntegerField(default=250)

    campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, related_name='listings', null=True, blank=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['title']


class ListingImage(models.Model):
    image = ProcessedImageField(
        processors=[
            Transpose(),
            ResizeToFill(1000, 1000)
        ],
        format='PNG',
        options={'quality': 60},
        upload_to=path_and_rename
    )
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='images')

    def __str__(self):
        return f'Image {self.id}'


class Offer(models.Model):
    posh_user = models.ForeignKey(PoshUser, on_delete=models.CASCADE, related_name='offers')
    listing_title = models.CharField(max_length=50)

    datetime_sent = models.DateTimeField()
    amount = models.PositiveIntegerField()

    def __str__(self):
        return f'Offer {self.id}'


class ProxyConnection(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField()
    in_use = models.BooleanField(default=True)
    proxy_license_uuid = models.UUIDField()
    proxy_name = models.CharField(max_length=255)

    @staticmethod
    def authenticate():
        login_response = requests.post(
            'https://portal.mobilehop.com/login',
            data={'username': os.environ.get('PROXY_USERNAME'), 'password': os.environ.get('PROXY_PASSWORD')}
        )

        if login_response.status_code == requests.codes.ok:
            return login_response.cookies
        else:
            return None

    def fast_reset(self, proxy_license_uuid=None):
        cookies = self.authenticate()
        if not proxy_license_uuid:
            proxy_license_uuid = self.proxy_license_uuid
        response = requests.get(f'https://portal.mobilehop.com/api/v2/proxies/reset/{proxy_license_uuid}',
                                cookies=cookies)

        return response.text

    def hard_rest(self, proxy_license_uuid=None):
        cookies = self.authenticate()
        if not proxy_license_uuid:
            proxy_license_uuid = self.proxy_license_uuid
        response = requests.get(f'https://portal.mobilehop.com/api/v2/proxies/hard_reset/{proxy_license_uuid}',
                                cookies=cookies)

        return response.text

    def __str__(self):
        return f'{self.campaign.title} on {self.proxy_name}'