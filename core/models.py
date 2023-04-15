import boto3
import datetime
import logging
import os
import random
import requests
import pytz
import string

from dateutil.parser import parse
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from faker import Faker
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFill, Transpose
from ppadb.client import Client as AdbClient
from uuid import uuid4


def path_and_rename(instance, filename):
    ext = filename.split('.')[-1]
    rand_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    filename = None
    path = None
    aws_session = boto3.Session()
    s3_client = aws_session.resource('s3', aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
                                     aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
                                     region_name=settings.AWS_S3_REGION_NAME)

    while not filename:
        if isinstance(instance, Listing):
            title = instance.title.replace(' ', '_')
            filename = f'cover_photo_{rand_str}.{ext}'
            path = os.path.join(instance.user.username, 'listing_images', title, filename)

        elif isinstance(instance, ListingImage):
            title = instance.listing.title.replace(' ', '_')
            filename = f'image_{rand_str}.{ext}'
            path = os.path.join(instance.listing.user.username, 'listing_images', title, filename)

        elif isinstance(instance, PoshUser):
            filename = f'image_{rand_str}.{ext}'
            path = os.path.join(instance.user.username, 'posh_user_images', filename)

        elif isinstance(instance, LogEntry):
            filename = f'image_{rand_str}.{ext}'
            path = os.path.join(instance.log_group.campaign.user.username, 'log_images',
                                instance.log_group.campaign.title, instance.log_group.campaign.posh_user.username,
                                filename)

        try:
            s3_client.Object(settings.AWS_STORAGE_BUCKET_NAME, path).load()
            filename = None
            rand_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        except Exception:
            pass

    return path


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    checked_out_by = models.UUIDField(blank=True, null=True)
    serial = models.CharField(max_length=12, unique=True)
    ip_reset_url = models.URLField()

    is_active = models.BooleanField(default=True)

    checkout_time = models.DateTimeField(null=True, blank=True)

    system_port = models.SmallIntegerField(unique=True)
    mjpeg_server_port = models.SmallIntegerField(unique=True)
    installed_clones = models.SmallIntegerField(default=0)

    def is_ready(self):
        if not self.is_active:
            return False

        if self.checked_out_by:
            return False

        logger = logging.getLogger(__name__)

        try:
            client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
            adb_device = client.device(serial=self.serial)

            if adb_device:
                ready = adb_device.shell('getprop sys.boot_completed').strip() == '1'
                current_time_str = adb_device.shell('date').strip()
                current_time = parse(current_time_str).replace(tzinfo=pytz.utc)
                boot_time_str = adb_device.shell('uptime -s').strip()

                boot_time = datetime.datetime.strptime(boot_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=current_time.tzinfo)

                if ready and (current_time - boot_time).total_seconds() > 10:
                    return True

            return False
        except RuntimeError as e:
            logger.error(e, exc_info=True)
            return False

    def check_out(self, campaign_id: uuid4):
        """Check out the device for use by a posh user."""
        if not self.is_ready():
            raise ValueError('Device is already in use')

        self.checked_out_by = campaign_id
        self.checkout_time = timezone.now()
        self.save(update_fields=['checked_out_by', 'checkout_time'])

    def check_in(self):
        """Check in the device after use."""
        self.checked_out_by = None
        self.checkout_time = None
        self.save(update_fields=['checked_out_by', 'checkout_time'])

    def __str__(self):
        return self.serial


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
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True, default=None)

    username = models.CharField(max_length=15, unique=True, blank=True)
    password = models.CharField(max_length=20,
                                help_text='Must be at least 6 characters and must contain a number or symbol.')
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    gender = models.CharField(max_length=2, choices=GENDER_CHOICES, blank=True)
    phone_number = models.CharField(max_length=20, default='', blank=True)
    profile_picture_id = models.CharField(max_length=200, blank=True)
    app_package = models.CharField(max_length=100, blank=True)

    profile_picture = models.ImageField(upload_to=path_and_rename, null=True, blank=True)
    header_picture = models.ImageField(upload_to=path_and_rename, null=True, blank=True)

    email = models.EmailField(blank=True)

    date_added = models.DateField(auto_now_add=True)
    date_disabled = models.DateField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_active_in_posh = models.BooleanField(default=True)
    is_registered = models.BooleanField(default=False)
    profile_updated = models.BooleanField(default=False)
    clone_installed = models.BooleanField(default=False)
    finished_registration = models.BooleanField(default=False)

    time_to_install_clone = models.DurationField(default=datetime.timedelta(seconds=0), blank=True)
    time_to_register = models.DurationField(default=datetime.timedelta(seconds=0), blank=True)
    time_to_finish_registration = models.DurationField(default=datetime.timedelta(seconds=0), blank=True)

    zipcode = models.IntegerField(blank=True)

    @property
    def status(self):
        if not self.is_active:
            return 'Disabled'

        if not self.is_active_in_posh:
            return 'Inactive'

        assigned_campaign = Campaign.objects.filter(posh_user=self)

        if not assigned_campaign:
            return 'Unassigned'
        elif self.campaign and self.campaign.status == Campaign.RUNNING:
            return 'Running'
        elif self.campaign:
            return 'Assigned'

    @property
    def sold_listings(self):
        sold_listings = ListedItem.objects.filter(posh_user=self, status=ListedItem.SOLD)

        return sold_listings.count()

    @property
    def last_sale_time(self):
        last_sale = ListedItem.objects.filter(posh_user=self, status=ListedItem.SOLD).order_by('-datetime_sold').first()

        if last_sale:
            return last_sale.datetime_sold.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

        return None

    @staticmethod
    def _generate_username(faker_obj, first_name, last_name):
        # Split the names into separate words
        first_name_words = first_name.lower().split()
        last_name_words = last_name.lower().split()

        # Initialize the username with the first letter of the first name
        first_letter = first_name_words[0][0]
        username = first_letter

        # Add a random name word, last name, or random word to the username
        choices = first_name_words + last_name_words + [faker_obj.word()]
        name_choice = random.choice(choices)
        if name_choice[0] != first_letter:
            username += name_choice
        else:
            # Choose a different name or word
            choices.remove(name_choice)
            username += random.choice(choices)

        # Add a random lowercase letter to the username
        username += random.choice(string.ascii_lowercase)

        # Add a random number to the end of the username (with 60% probability)
        if random.random() < 0.6:
            username += str(faker_obj.random_int(min=10, max=99))

        # Truncate the username if it is longer than 15 characters
        if len(username) > 15:
            username = username[:15]

        return username

    @staticmethod
    def generate(user, email, password):
        fake = Faker()
        attempts = 0
        profile_picture_id = fake.random_int(min=1, max=1000)

        while attempts < 10 and PoshUser.objects.filter(profile_picture_id=profile_picture_id).exists():
            profile_picture_id = fake.random_int(min=1, max=1000)

        profile_picture_url = f'https://picsum.photos/id/{profile_picture_id}/600'
        header_picture_url = f'https://picsum.photos/1920/300'

        profile_picture_content = requests.get(profile_picture_url).content
        profile_picture_file = ContentFile(profile_picture_content)

        header_picture_content = requests.get(header_picture_url).content
        header_picture_file = ContentFile(header_picture_content)

        first_name = fake.first_name()
        last_name = fake.last_name()

        username = PoshUser._generate_username(fake, first_name, last_name)

        posh_user = PoshUser.objects.create(
            user=user,
            first_name=first_name,
            last_name=last_name,
            username=username,
            password=password,
            gender=fake.random_element(elements=('M', 'F')),
            email=email,
            date_of_birth=fake.date_of_birth(minimum_age=18, maximum_age=30),
            zipcode=fake.zipcode_in_state('FL'),
            profile_picture=profile_picture_file,
            header_picture=header_picture_file
        )

        return posh_user

    def __str__(self):
        return self.username

    class Meta:
        ordering = ['username']


class Campaign(models.Model):
    RUNNING = 'RUNNING'
    IDLE = 'IDLE'
    STOPPED = 'STOPPED'
    STARTING = 'STARTING'
    STOPPING = 'STOPPING'
    PAUSED = 'PAUSED'
    IN_QUEUE = 'IN QUEUE'

    STATUS_CHOICES = [
        (RUNNING, 'RUNNING'),
        (IDLE, 'IDLE'),
        (STOPPED, 'STOPPED'),
        (STARTING, 'STARTING'),
        (STOPPING, 'STOPPING'),
        (PAUSED, 'PAUSED'),
        (IN_QUEUE, 'IN QUEUE'),
    ]

    ADVANCED_SHARING = '0'
    BASIC_SHARING = '1'
    BOT_TESTS = '2'
    REGISTER = '3'

    MODE_CHOICES = [
        (ADVANCED_SHARING, 'Advanced Sharing'),
        (BASIC_SHARING, 'Basic Sharing'),
        (BOT_TESTS, 'Bot Tests'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    posh_user = models.OneToOneField(PoshUser, on_delete=models.SET_NULL, blank=True, null=True)

    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='0')
    title = models.CharField(max_length=30)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STOPPED)
    queue_status = models.CharField(max_length=15, default='N/A')

    delay = models.SmallIntegerField()
    lowest_price = models.SmallIntegerField(default=250)

    auto_run = models.BooleanField(default=True)
    generate_users = models.BooleanField(default=True)

    next_runtime = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['title']


class Listing(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    title = models.CharField(max_length=80)
    size = models.CharField(max_length=20)
    brand = models.CharField(max_length=30, blank=True)
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


class ListedItem(models.Model):
    NOT_LISTED = 'NOT LISTED'
    UP = 'UP'
    UNDER_REVIEW = 'UNDER REVIEW'
    RESERVED = 'RESERVED'
    SOLD = 'SOLD'
    REMOVED = 'REMOVED'

    STATUS_CHOICES = [
        (NOT_LISTED, NOT_LISTED),
        (UP, UP),
        (UNDER_REVIEW, UNDER_REVIEW),
        (RESERVED, RESERVED),
        (SOLD, SOLD),
        (REMOVED, REMOVED)
    ]

    posh_user = models.ForeignKey(PoshUser, on_delete=models.CASCADE)
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True, blank=True)

    listing_title = models.CharField(max_length=50)
    datetime_listed = models.DateTimeField(null=True, blank=True)
    datetime_passed_review = models.DateTimeField(null=True, blank=True)
    datetime_removed = models.DateTimeField(null=True, blank=True)
    datetime_sold = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=255, choices=STATUS_CHOICES, default=NOT_LISTED)

    time_to_list = models.DurationField(default=datetime.timedelta(seconds=0), blank=True)

    def __str__(self):
        return f'{self.listing_title}'


class Offer(models.Model):
    posh_user = models.ForeignKey(PoshUser, on_delete=models.CASCADE, related_name='offers')
    listing_title = models.CharField(max_length=50)

    datetime_sent = models.DateTimeField()
    amount = models.PositiveIntegerField()

    def __str__(self):
        return f'Offer {self.id}'


class LogGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    posh_user = models.ForeignKey(PoshUser, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)

    def log(self, message, log_level=None, image=None):
        timestamp = timezone.now()

        log_entry = LogEntry(
            level=log_level if log_level else LogEntry.NOTSET,
            log_group=self,
            timestamp=timestamp,
            message=message
        )
        if image:
            with open(image, 'rb') as image_file:
                log_entry.image.save(image, ContentFile(image_file.read()), save=False)

        log_entry.save()

    def critical(self, message, image=None):
        self.log(message, LogEntry.CRITICAL, image)

    def error(self, message, image=None):
        self.log(message, LogEntry.ERROR, image)

    def warning(self, message, image=None):
        self.log(message, LogEntry.WARNING, image)

    def info(self, message, image=None):
        self.log(message, LogEntry.INFO, image)

    def debug(self, message, image=None):
        self.log(message, LogEntry.DEBUG, image)

    def __str__(self):
        return f'LogGroup {self.campaign.title} for {self.posh_user.username}'

    class Meta:
        ordering = ['-created_date']


class LogEntry(models.Model):
    CRITICAL = 50
    ERROR = 40
    WARNING = 30
    INFO = 20
    DEBUG = 10
    NOTSET = 0

    LOG_LEVELS = [
        (NOTSET, ''),
        (DEBUG, 'DEBUG'),
        (INFO, 'INFO'),
        (WARNING, 'WARNING'),
        (ERROR, 'ERROR'),
        (CRITICAL, 'CRITICAL'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    level = models.IntegerField()
    log_group = models.ForeignKey(LogGroup, on_delete=models.CASCADE, related_name='log_entries')
    timestamp = models.DateTimeField()
    message = models.TextField()
    image = ProcessedImageField(
        format='PNG',
        options={'quality': 60},
        upload_to=path_and_rename
    )
