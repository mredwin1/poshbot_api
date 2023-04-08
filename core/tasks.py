import datetime
import logging
import os
import pytz
import random
import requests
import time
import traceback

from celery import shared_task, Task
from django.utils import timezone
from ppadb.client import Client as AdbClient
from selenium.common.exceptions import WebDriverException

from appium_clients.clients import AppClonerClient, PoshMarkClient as MobilePoshMarkClient
from chrome_clients.clients import PoshMarkClient, PublicPoshMarkClient
from poshbot_api.celery import app
from .models import Campaign, Listing, ListingImage, PoshUser, Device, LogGroup, ListedItem


class CampaignTask(Task):
    def __init__(self):
        self.campaign = None
        self.logger = None
        self.device = None

    def get_random_delay(self, elapsed_time):
        delay = self.campaign.delay * 60

        if delay <= 0:
            return 0
        else:
            range_start = max(0, delay - (delay * 0.3))
            range_end = delay + (delay * 0.3)
            random_delay_in_seconds = round(random.uniform(range_start, range_end))
            delay_after_elapsed_time_in_seconds = random_delay_in_seconds - elapsed_time
            if delay_after_elapsed_time_in_seconds >= 0:
                return delay_after_elapsed_time_in_seconds
            else:
                return random_delay_in_seconds

    def launch_app(self, client):
        app_launched = False
        retries = 0

        while not app_launched and retries < 2:
            app_launched = client.launch_app(self.campaign.posh_user.username)
            retries += 1

        if not app_launched and not self.campaign.posh_user.is_registered:
            self.campaign.posh_user.clone_installed = False
            self.campaign.posh_user.save(update_fields=['clone_installed'])

            return False

        return app_launched

    def reset_ip(self, reset_url):
        response = requests.get(reset_url)
        retries = 0

        while response.status_code != requests.codes.ok and retries < 3:
            self.logger.warning('IP reset failed, trying again')
            response = requests.get(reset_url)
            retries += 1
            time.sleep(1)

        if response.status_code == requests.codes.ok:
            self.logger.info(response.text)
            return True

        self.logger.info(f'Could not reset IP after {retries} retries. Sending campaign to the end of the line')

        self.campaign.status = Campaign.STARTING
        self.campaign.queue_status = 'Unknown'
        self.campaign.next_runtime = timezone.now()
        self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])

        return False

    def init_logger(self, logger_id=None):
        if logger_id:
            self.logger = LogGroup.objects.get(id=logger_id)
        else:
            self.logger = LogGroup(campaign=self.campaign, posh_user=self.campaign.posh_user, created_date=timezone.now())
            self.logger.save()

    def install_clone(self, device):
        with AppClonerClient(device.serial, device.system_port, device.mjpeg_server_port, self.logger, self.campaign.posh_user.username) as client:
            if not self.campaign.posh_user.clone_installed:
                start_time = time.time()
                installed = client.add_clone()
                end_time = time.time()
                if installed:
                    time_to_install = datetime.timedelta(seconds=round(end_time - start_time))

                    self.logger.info(f'Time to install clone: {time_to_install}')

                self.campaign.posh_user.clone_installed = installed
                self.campaign.posh_user.device = device
                self.campaign.posh_user.time_to_install_clone = time_to_install
                self.campaign.posh_user.save(update_fields=['clone_installed', 'device', 'time_to_install_clone'])

                device.refresh_from_db(fields=['installed_clones'])
                device.installed_clones += 1
                device.save(update_fields=['installed_clones'])

            if not self.campaign.posh_user.app_package:
                app_launched = self.launch_app(client)

                if not app_launched:
                    return False

                clone_app_package = client.driver.current_package

                while 'poshmark' not in clone_app_package:
                    self.logger.info(f'App did not launch properly. Current app package {clone_app_package}')
                    app_launched = self.launch_app(client)

                    if not app_launched:
                        return False

                    time.sleep(.5)
                    clone_app_package = client.driver.current_package

                self.campaign.posh_user.app_package = clone_app_package
                self.campaign.posh_user.save(update_fields=['app_package'])

        return self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package

    def register(self, list_items, device):
        ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            with MobilePoshMarkClient(device.serial, device.system_port, device.mjpeg_server_port, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                if client.driver.current_package != self.campaign.posh_user.app_package:
                    app_launched = self.launch_app(client)

                    if not app_launched:
                        return False

                start_time = time.time()
                registered = client.register()
                end_time = time.time()

                if registered:
                    time_to_register = datetime.timedelta(seconds=round(end_time - start_time))

                    self.campaign.posh_user.time_to_register = time_to_register
                    self.logger.info(f'Time to register user: {time_to_register}')

                self.campaign.posh_user.is_registered = registered
                self.campaign.posh_user.save(update_fields=['time_to_register', 'is_registered'])

                if registered:
                    finish_registration_and_list = self.finish_registration(device, list_items, False, client)

                client.driver.press_keycode(3)

            if not (registered and finish_registration_and_list):
                self.logger.info('Restarting campaign due to error')
                self.campaign.status = Campaign.STARTING
                self.campaign.queue_status = 'Unknown'
                self.campaign.next_runtime = timezone.now()
                self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])

                return False

            return True

        return False

    def finish_registration(self, device, list_items=True, reset_ip=True, client=None):
        ip_reset = not reset_ip
        listed = not list_items

        if reset_ip:
            ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            if client:
                start_time = time.time()
                registration_finished = client.finish_registration()
                end_time = time.time()

                if registration_finished:
                    time_to_finish_registration = datetime.timedelta(seconds=round(end_time - start_time))
                    self.campaign.posh_user.time_to_finish_registration = time_to_finish_registration
                    self.logger.info(f'Time to finish registration: {time_to_finish_registration} seconds')

                self.campaign.posh_user.finished_registration = registration_finished
                self.campaign.posh_user.save(update_fields=['time_to_finish_registration', 'finished_registration'])

                if registration_finished and list_items:
                    listed = self.list_items(device, False, client)

                client.driver.press_keycode(3)
            else:
                with MobilePoshMarkClient(device.serial, device.system_port, device.mjpeg_server_port, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                    if client.driver.current_package != self.campaign.posh_user.app_package:
                        app_launched = self.launch_app(client)

                        if not app_launched:
                            return False

                    start_time = time.time()
                    registration_finished = client.finish_registration()
                    end_time = time.time()

                    if registration_finished:
                        time_to_finish_registration = datetime.timedelta(seconds=round(end_time - start_time))

                        self.campaign.posh_user.time_to_finish_registration = time_to_finish_registration
                        self.logger.info(f'Time to finish registration: {time_to_finish_registration}')

                    self.campaign.posh_user.finished_registration = registration_finished
                    self.campaign.posh_user.save(update_fields=['time_to_finish_registration', 'finished_registration'])

                    if registration_finished and list_items:
                        listed = self.list_items(device, False, client)

                    client.driver.press_keycode(3)

            if not (registration_finished and listed):
                self.logger.info('Did not list properly or finish registration. Restarting campaign')
                self.campaign.status = Campaign.STARTING
                self.campaign.queue_status = 'Unknown'
                self.campaign.next_runtime = timezone.now()
                self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])
                return False

            return True

        return False

    def list_items(self, device, reset_ip=True, client=None):
        ip_reset = not reset_ip

        if reset_ip:
            ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            item_listed = False
            items_to_list = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED)

            if client:
                for item_to_list in items_to_list:
                    listing_images = ListingImage.objects.filter(listing=item_to_list.listing)

                    start_time = time.time()
                    item_listed = client.list_item(item_to_list.listing, listing_images)
                    end_time = time.time()
                    time_to_list = datetime.timedelta(seconds=round(end_time - start_time))

                    if item_listed:
                        self.logger.info(f'Time to list item: {time_to_list}')

                        item_to_list.time_to_list = time_to_list
                        item_to_list.status = ListedItem.UNDER_REVIEW
                        item_to_list.datetime_listed = timezone.now()
                        item_to_list.save(update_fields=['time_to_list', 'status', 'datetime_listed'])
            else:
                with MobilePoshMarkClient(device.serial, device.system_port, device.mjpeg_server_port, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                    if client.driver.current_package != self.campaign.posh_user.app_package:
                        app_launched = self.launch_app(client)

                        if not app_launched:
                            return False

                    for item_to_list in items_to_list:
                        listing_images = ListingImage.objects.filter(listing=item_to_list.listing)

                        start_time = time.time()
                        listed = client.list_item(item_to_list.listing, listing_images)
                        end_time = time.time()
                        time_to_list = datetime.timedelta(seconds=round(end_time - start_time))

                        if listed:
                            self.logger.info(f'Time to list item: {time_to_list}')

                            item_to_list.time_to_list = time_to_list
                            item_to_list.status = ListedItem.UNDER_REVIEW
                            item_to_list.datetime_listed = timezone.now()
                            item_to_list.save(update_fields=['time_to_list', 'status', 'datetime_listed'])

                            if not item_listed:
                                item_listed = listed

                    client.driver.press_keycode(3)

            if not item_listed:
                self.logger.info('Did not list successfully. Restarting campaign.')

                self.campaign.status = Campaign.STARTING
                self.campaign.queue_status = 'Unknown'
                self.campaign.next_runtime = timezone.now()
                self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])
            else:
                all_items = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.UP)

                if all_items.count() == 0:
                    self.campaign.status = Campaign.PAUSED
                    self.campaign.save(update_fields=['status'])

            return item_listed

    def share_and_more(self):
        login_retries = 0
        update_profile_retries = 0
        all_listings_retries = 0
        listing_shared_retries = 0
        profile_updated = self.campaign.posh_user.profile_updated
        all_listings = None
        listing_shared = None
        shared = None
        with PoshMarkClient(self.campaign, self.logger) as client:
            client.web_driver.get('https://poshmark.com')
            client.load_cookies()
            logged_in = client.check_logged_in()

            while not logged_in and login_retries < 3:
                logged_in = client.login(login_retries)
                login_retries += 1

            while not profile_updated and update_profile_retries < 3 and logged_in:
                profile_updated = client.update_profile(update_profile_retries)
                update_profile_retries += 1

            if profile_updated:
                self.campaign.posh_user.profile_updated = True
                self.campaign.posh_user.save(update_fields=['profile_updated'])

            if logged_in:
                while all_listings is None and all_listings_retries < 3:
                    all_listings = client.get_all_listings()
                    all_listings_retries += 1

                if all_listings:
                    listing_titles = all_listings['shareable_listings'] + all_listings['sold_listings'] + all_listings['reserved_listings']
                    listings_can_share = []

                    for listing_title in listing_titles:
                        try:
                            listed_item = ListedItem.objects.get(posh_user=self.campaign.posh_user, listing_title=listing_title)

                            if listing_title in all_listings['shareable_listings']:
                                if listed_item.status != ListedItem.UP:
                                    listed_item.status = ListedItem.UP
                                    listed_item.save(update_fields=['status'])
                                listings_can_share.append(listing_title)
                            elif listing_title in all_listings['sold_listings'] and not listed_item.datetime_sold:
                                listed_item.datetime_sold = timezone.now()
                                listed_item.status = ListedItem.SOLD
                                listed_item.save(update_fields=['status', 'datetime_sold'])
                            elif listing_title in all_listings['reserved_listings'] and listed_item.status != ListedItem.RESERVED:
                                listed_item.status = ListedItem.RESERVED
                                listed_item.save(update_fields=['status'])

                        except ListedItem.DoesNotExist:
                            self.logger.warning(f'Could not find a listed item for {self.campaign.posh_user} with title {listing_title}. Creating it now...')

                            try:
                                listing = Listing.objects.get(title=listing_title)
                            except Listing.DoesNotExist:
                                listing = None

                            listed_item = ListedItem(posh_user=self.campaign.posh_user, listing=listing, listing_title=listing_title)

                            if listing_title in all_listings['reserved_listings']:
                                listed_item.status = ListedItem.RESERVED
                            elif listing_title in all_listings['sold_listings']:
                                listed_item.datetime_sold = timezone.now()
                                listed_item.status = ListedItem.SOLD
                            else:
                                listed_item.status = ListedItem.UP
                                listings_can_share.append(listing_title)

                            listed_item.save()
                        except ListedItem.MultipleObjectsReturned:
                            pass

                    if listings_can_share:
                        for listing_title in listings_can_share:
                            while listing_shared is None and listing_shared_retries < 3:
                                listing_shared = client.share_item(listing_title)
                                listing_shared_retries += 1

                            if not shared:
                                shared = listing_shared
                            listing_shared = None

                            if random.random() < .20 and shared:
                                self.logger.info('Seeing if it is time to send offers to likers')
                                now = timezone.now()
                                nine_pm = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=2,
                                                            minute=0, second=0).replace(tzinfo=pytz.utc)
                                midnight = nine_pm + datetime.timedelta(hours=3)

                                if nine_pm < now < midnight:
                                    client.send_offer_to_likers(listing_title)
                                else:
                                    self.logger.info(f"Not the time to send offers to likers. Current Time: {now.astimezone(pytz.timezone('US/Eastern')).strftime('%I:%M %p')} Eastern")

                            if random.random() < .20 and shared:
                                client.check_offers(listing_title)

                        return shared

                    elif all_listings['reserved_listings']:
                        self.logger.info('There are only reserved listing on this user\'s account.')

                        return False

                    elif not listings_can_share and all_listings['shareable_listings']:
                        self.logger.info('The remaining listings are under review. Pausing campaign.')

                        self.campaign.status = Campaign.PAUSED
                        self.campaign.save(update_fields=['status'])

                        return False
                    else:
                        self.logger.info('There are no listings on this user\'s account. Stopping campaign.')

                        self.campaign.status = Campaign.STOPPED
                        self.campaign.save(update_fields=['status'])

                        return False
            else:
                self.logger.info('Stopping campaign because user could not log in')

                self.campaign.status = Campaign.STOPPED
                self.campaign.save(update_fields=['status'])
                return False

    def run(self, campaign_id, logger_id=None, device_id=None, attempt=1, *args, **kwargs):
        self.campaign = Campaign.objects.get(id=campaign_id)
        campaign_delay = None
        success = False

        self.init_logger(logger_id)

        if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED) and self.campaign.posh_user:
            self.logger.info(f'Campaign, {self.campaign.title}, started for {self.campaign.posh_user.username}')

            try:
                self.device = Device.objects.get(id=device_id)
            except Device.DoesNotExist:
                pass

            self.campaign.status = Campaign.RUNNING
            self.campaign.queue_status = 'N/A'
            self.campaign.save(update_fields=['status', 'queue_status'])

            items_to_list = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED)
            need_to_list = items_to_list.count() > 0

            start_time = time.time()
            try:
                if not (self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package) and self.device and self.campaign.mode == Campaign.ADVANCED_SHARING:
                    installed = self.install_clone(self.device)
                elif self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package and self.device and self.campaign.mode == Campaign.ADVANCED_SHARING:
                    installed = True
                else:
                    installed = False

                if installed and not self.campaign.posh_user.is_registered:
                    success = self.register(device=self.device, list_items=need_to_list)
                elif installed and not self.campaign.posh_user.finished_registration:
                    success = self.finish_registration(device=self.device, list_items=need_to_list, reset_ip=True)
                elif installed and items_to_list:
                    success = self.list_items(self.device)
                elif self.campaign.posh_user.is_registered and self.campaign.mode in (Campaign.ADVANCED_SHARING, Campaign.BASIC_SHARING):
                    success = self.share_and_more()
                else:
                    self.campaign.status = Campaign.STOPPING
                    self.campaign.save(update_fields=['status'])

                    success = False
            except WebDriverException:
                self.logger.debug(traceback.format_exc())
                success = False

                client = AdbClient(host=os.environ.get('LOCAL_SERVER_IP'), port=5037)
                adb_device = client.device(serial=self.device.serial)

                adb_device.reboot()

                self.logger.warning(f'Sending campaign to the end of the line due to an error')

                self.campaign.status = Campaign.STARTING
                self.campaign.next_runtime = timezone.now()
                self.campaign.queue_status = 'Unknown'
                self.campaign.save(update_fields=['status', 'next_runtime', 'queue_status'])
            except Exception:
                self.logger.debug(traceback.format_exc())
                self.logger.error('Sending campaign to the end of the line due to an unhandled error')

                self.campaign.status = Campaign.STARTING
                self.campaign.next_runtime = timezone.now()
                self.campaign.queue_status = 'Unknown'
                self.campaign.save(update_fields=['status', 'next_runtime', 'queue_status'])

            end_time = time.time()

            if not self.campaign.posh_user.is_active_in_posh:
                self.campaign.status = Campaign.STOPPED
                self.campaign.save(update_fields=['status'])

            if self.device:
                self.logger.info('Releasing device')
                self.device.check_in()

            if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED, Campaign.PAUSED, Campaign.STARTING):
                if not success and self.campaign.status not in (Campaign.STOPPED, Campaign.STOPPING):
                    campaign_delay = 3600

                if not campaign_delay:
                    campaign_delay = self.get_random_delay(end_time - start_time)

                hours, remainder = divmod(campaign_delay, 3600)
                minutes, seconds = divmod(remainder, 60)

                self.campaign.status = Campaign.IDLE
                self.campaign.next_runtime = timezone.now() + datetime.timedelta(seconds=campaign_delay)
                self.campaign.save(update_fields=['status', 'next_runtime'])
                self.logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')

        self.logger.info('Campaign ended')


CampaignTask = app.register_task(CampaignTask())


def get_available_device(excluded_device_ids):
    devices = Device.objects.filter(is_active=True).exclude(id__in=excluded_device_ids)
    in_use_ip_reset_urls = Device.objects.exclude(in_use='').values_list('ip_reset_url', flat=True)

    for device in devices:
        if device.ip_reset_url not in in_use_ip_reset_urls:
            if device.is_ready():
                return device
        else:
            if device.checkout_time is not None and (timezone.now() - device.checkout_time).total_seconds() > 1200:
                log = LogGroup.objects.filter(posh_user__username=device.in_use).first()
                log.warning('Another campaign will be started on this device because this one took too long.')
                device.check_in()

                in_use_ip_reset_urls = Device.objects.exclude(in_use='').values_list('ip_reset_url', flat=True)

                if device.ip_reset_url not in in_use_ip_reset_urls:
                    if device.is_ready():
                        return device


@shared_task
def start_campaigns():
    logger = logging.getLogger(__name__)
    campaigns = Campaign.objects.filter(status__in=[Campaign.STOPPING, Campaign.IDLE, Campaign.STARTING], posh_user__isnull=False).order_by('next_runtime')
    now = timezone.now()
    queue_num = 1
    excluded_device_ids = []

    for campaign in campaigns:
        available_device = None
        items_to_list = ListedItem.objects.filter(posh_user=campaign.posh_user, status=ListedItem.NOT_LISTED)

        if campaign.status == Campaign.STOPPING:
            campaign.status = Campaign.STOPPED
            campaign.queue_status = 'N/A'
            campaign.next_runtime = None
            campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])
        elif campaign.status == Campaign.IDLE and campaign.next_runtime is not None and campaign.next_runtime <= now:
            campaign.status = Campaign.IN_QUEUE
            campaign.queue_status = 'N/A'
            campaign.save(update_fields=['status', 'queue_status'])
            CampaignTask.delay(campaign.id)
        elif campaign.status == Campaign.STARTING and campaign.posh_user.is_registered and items_to_list.count() == 0:
            campaign.status = Campaign.IN_QUEUE
            campaign.queue_status = 'N/A'
            campaign.save(update_fields=['status', 'queue_status'])
            CampaignTask.delay(campaign.id)
        elif campaign.status == Campaign.STARTING and (not campaign.posh_user.is_registered or items_to_list.count() > 0):
            if queue_num == 1:
                available_device = get_available_device(excluded_device_ids)

            if available_device:
                excluded_device_ids.append(available_device.id)
                try:
                    available_device.check_out(campaign.posh_user.username)
                    campaign.status = Campaign.IN_QUEUE
                    campaign.queue_status = 'N/A'
                    campaign.save(update_fields=['status', 'queue_status'])
                    CampaignTask.delay(campaign.id, device_id=available_device.id)
                    logger.info(f'Campaign Started: {campaign.title} for {campaign.posh_user.username} on {available_device}')
                    time.sleep(5)
                except ValueError:
                    logger.info(f'Device: {available_device} is not ready')
            else:
                campaign.queue_status = str(queue_num)
                campaign.save(update_fields=['queue_status'])
                queue_num += 1


@shared_task
def check_posh_users():
    logger = logging.getLogger(__name__)
    logger.info('Checking posh users')
    posh_users = PoshUser.objects.filter(is_active_in_posh=True, is_registered=True)
    with PublicPoshMarkClient(logger) as client:
        for posh_user in posh_users:
            try:
                campaign = Campaign.objects.get(posh_user=posh_user)
            except Campaign.DoesNotExist:
                campaign = None

            all_listings = client.get_all_listings(posh_user.username)
            if all_listings:
                listing_titles = all_listings['shareable_listings'] + all_listings['sold_listings'] + all_listings['reserved_listings']

                for listing_title in listing_titles:
                    try:
                        listed_item = ListedItem.objects.get(posh_user=posh_user, listing_title=listing_title)

                        if listing_title in all_listings['shareable_listings'] and listed_item.status != ListedItem.UP:
                            if listed_item.status == ListedItem.UNDER_REVIEW:
                                listed_item.datetime_passed_review = timezone.now()
                                listed_item.status = ListedItem.UP
                                listed_item.save(update_fields=['status', 'datetime_passed_review'])
                            elif listed_item.status != ListedItem.UNDER_REVIEW and (not campaign or campaign.status not in (Campaign.IDLE, Campaign.RUNNING, Campaign.STARTING)):
                                listed_item.status = ListedItem.UP
                                listed_item.save(update_fields=['status'])

                        elif listing_title in all_listings['sold_listings'] and listed_item.status != ListedItem.SOLD:
                            listed_item.datetime_sold = timezone.now()
                            listed_item.status = ListedItem.SOLD

                            listed_item.save(update_fields=['status', 'datetime_sold'])
                        elif listing_title in all_listings['reserved_listings'] and listed_item.status != ListedItem.RESERVED:
                            listed_item.status = ListedItem.RESERVED
                            listed_item.save(update_fields=['status'])

                    except ListedItem.DoesNotExist:
                        logger.warning(f'Could not find a listed item for {posh_user} with title {listing_title}.')

                        if not campaign or campaign.status not in (Campaign.IDLE, Campaign.RUNNING, Campaign.STARTING):
                            logger.warning(f'Creating the listed item now...')

                            try:
                                listing = Listing.objects.get(title=listing_title)
                            except Listing.DoesNotExist:
                                listing = None

                            listed_item = ListedItem(posh_user=posh_user, listing=listing, listing_title=listing_title)

                            if listing_title in all_listings['reserved_listings']:
                                listed_item.status = ListedItem.RESERVED
                            elif listing_title in all_listings['sold_listings']:
                                listed_item.datetime_sold = timezone.now()
                                listed_item.status = ListedItem.SOLD
                            else:
                                listed_item.status = ListedItem.UP

                            listed_item.save()
                    except ListedItem.MultipleObjectsReturned:
                        pass

                if (all_listings['shareable_listings'] or all_listings['reserved_listings']) and campaign and campaign.status == Campaign.PAUSED:
                    logger.info('User has shareable listings and its campaign is paused. Resuming...')
                    campaign.next_runtime = timezone.now()
                    campaign.queue_status = 'CALCULATING'
                    campaign.status = Campaign.STARTING
                    campaign.save(update_fields=['next_runtime', 'queue_status', 'status'])

            # Checks if the user is inactive when there are no listings and
            if sum([len(y) for y in all_listings.values()]) == 0 and (not campaign or campaign.status not in (Campaign.IDLE, Campaign.RUNNING, Campaign.STARTING)):
                logger.info('User has no listings available...')
                is_active_in_posh = client.check_inactive(posh_user.username)

                if not is_active_in_posh:
                    posh_user.is_active_in_posh = False
                    posh_user.save(update_fields=['is_active_in_posh'])

                    if campaign:
                        logger.info('Stopping campaign...')
                        campaign.status = Campaign.STOPPED
                        campaign.save(update_fields=['status'])


@shared_task
def log_cleanup():
    campaigns = Campaign.objects.all()

    for campaign in campaigns:
        logs = LogGroup.objects.filter(campaign=campaign).order_by('-created_date')[5:]

        for log in logs:
            log.delete()


@shared_task
def posh_user_cleanup():
    day_ago = timezone.now() - datetime.timedelta(days=1)
    two_weeks_ago = timezone.now() - datetime.timedelta(days=14)

    # Get all posh_users who have been inactive for at least a day
    posh_users = PoshUser.objects.filter(is_active=False, date_disabled__lt=day_ago)

    # Get all sold items for the relevant posh_users
    sold_items = ListedItem.objects.filter(posh_user__in=posh_users, status=ListedItem.SOLD, date_sold__lt=day_ago)

    # Create a dictionary of posh_users and their last sale date
    last_sale_dates = {}
    for sold_item in sold_items:
        posh_user = sold_item.posh_user
        if posh_user not in last_sale_dates or last_sale_dates[posh_user] < sold_item.date_sold:
            last_sale_dates[posh_user] = sold_item.date_sold

    # Delete posh_users who have been inactive for at least 14 days, or who have not made a sale in the last day
    for posh_user in posh_users:
        if posh_user.date_disabled < two_weeks_ago or posh_user not in last_sale_dates or last_sale_dates[posh_user] < day_ago:
            posh_user.delete()
