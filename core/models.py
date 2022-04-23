import os
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

        return os.path.join(upload_to, path, filename)
    else:
        path = instance.listing.title
        filename = f'image.{ext}'

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

    username = models.CharField(max_length=15, unique=True)
    password = models.CharField(max_length=20,
                                help_text='Must be at least 6 characters and must contain a number or symbol.')
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    gender = models.CharField(max_length=2, choices=GENDER_CHOICES)
    phone_number = models.CharField(max_length=20, default='', blank=True)
    profile_picture_id = models.CharField(max_length=200)

    profile_picture = models.ImageField(upload_to='profile_pictures')
    header_picture = models.ImageField(upload_to='header_pictures')

    email = models.EmailField(unique=True)

    sales = models.PositiveSmallIntegerField(default=0, blank=True)

    date_added = models.DateField(auto_now_add=True)
    date_of_birth = models.DateField()

    is_registered = models.BooleanField(default=False)
    profile_updated = models.BooleanField(default=False)

    @property
    def status(self):
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

    MODE_CHOICES = [
        (ADVANCED_SHARING, 'Advanced Sharing'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    posh_user = models.OneToOneField(PoshUser, on_delete=models.SET_NULL, blank=True, null=True)

    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='0')
    title = models.CharField(max_length=30)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=IDLE)

    delay = models.SmallIntegerField()

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
