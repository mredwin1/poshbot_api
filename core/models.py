import boto3
import datetime
import mailslurp_client
import os
import pytz
import random
import string
import time

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFill, Transpose
from mailslurp_client.rest import ApiException
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

    in_use = models.CharField(max_length=15, blank=True)
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

        if self.in_use:
            return False

        try:
            client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
            adb_device = client.device(serial=self.serial)

            if adb_device:
                ready = adb_device.shell('getprop sys.boot_completed').strip() == '1'
                uptime = adb_device.shell('uptime -s')

                import logging
                logging.getLogger(__name__).info(uptime)

                time.sleep(10)

                if ready:
                    return True

            return False
        except RuntimeError:
            return False

    def check_out(self, posh_user_username):
        """Check out the device for use by a posh user."""
        if not self.is_ready():
            raise ValueError('Device is already in use')

        self.in_use = posh_user_username
        self.checkout_time = timezone.now()
        self.save(update_fields=['in_use', 'checkout_time'])

    def check_in(self):
        """Check in the device after use."""
        self.in_use = ''
        self.checkout_time = None
        self.save(update_fields=['in_use', 'checkout_time'])

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
    email_id = models.CharField(max_length=255, blank=True)

    sales = models.PositiveSmallIntegerField(default=0, blank=True)

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
    def get_mail_slurp_config():
        configuration = mailslurp_client.Configuration()
        configuration.api_key['x-api-key'] = os.environ['MAIL_SLURP_API_KEY']

        return configuration

    @staticmethod
    def check_email_availability(email):
        with mailslurp_client.ApiClient(PoshUser.get_mail_slurp_config()) as api_client:
            inbox_controller = mailslurp_client.InboxControllerApi(api_client)
            inboxes = inbox_controller.get_all_inboxes(page=0)

            all_emails = [content.email_address for content in inboxes.content]

            return email not in all_emails

    @staticmethod
    def create_email(first_name, last_name, forward_to=None):
        with mailslurp_client.ApiClient(PoshUser.get_mail_slurp_config()) as api_client:
            api_instance = mailslurp_client.InboxControllerApi(api_client)
            email = f'{first_name.lower()}_{last_name.lower()}@{os.environ["DOMAIN"]}'

            while not PoshUser.check_email_availability(email):
                email = f'{first_name.lower()}_{last_name.lower()}{random.randint(100, 999)}@{os.environ["DOMAIN"]}'
            inbox = api_instance.create_inbox(name=f'{first_name} {last_name}')

            if forward_to:
                PoshUser.create_email_forwarder(inbox.id, forward_to)

            return inbox.id, inbox.email_address

    @staticmethod
    def create_email_forwarder(inbox_id, forward_to):
        with mailslurp_client.ApiClient(PoshUser.get_mail_slurp_config()) as api_client:
            api_instance = mailslurp_client.InboxForwarderControllerApi(api_client)
            create_inbox_forwarder_options = mailslurp_client.CreateInboxForwarderOptions(field='SENDER', match='*', forward_to_recipients=[forward_to])

            try:
                api_response = api_instance.create_new_inbox_forwarder(
                    create_inbox_forwarder_options=create_inbox_forwarder_options,
                    inbox_id=inbox_id)
            except ApiException as e:
                print(f"Exception when calling InboxForwarderControllerApi->create_new_inbox_forwarder: {e}")

    def delete_email(self):
        if self.email_id:
            with mailslurp_client.ApiClient(self.get_mail_slurp_config()) as api_client:
                api_instance = mailslurp_client.InboxControllerApi(api_client)
                api_instance.delete_inbox(self.email_id)

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
