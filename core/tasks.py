import datetime
import logging
import os
import pytz
import random
import requests
import time
import traceback

from celery import shared_task, Task
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

        self.logger.info(f'Could not reset IP after {retries} retries')
        return False

    def init_logger(self, logger_id=None):
        if logger_id:
            self.logger = LogGroup.objects.get(id=logger_id)
        else:
            self.logger = LogGroup(campaign=self.campaign, posh_user=self.campaign.posh_user)
            self.logger.save()

    def install_clone(self, device):
        with AppClonerClient(device.serial, self.logger, self.campaign.posh_user.username) as client:
            if not self.campaign.posh_user.clone_installed:
                installed = client.add_clone()

                self.campaign.posh_user.clone_installed = installed
                self.campaign.posh_user.device = device
                self.campaign.posh_user.save()

            if not self.campaign.posh_user.app_package:
                client.launch_app(self.campaign.posh_user.username)

                clone_app_package = client.driver.current_package

                self.campaign.posh_user.app_package = clone_app_package
                self.campaign.posh_user.save()

        return self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package

    def register(self, list_items, device):
        ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            with MobilePoshMarkClient(device.serial, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                client.launch_app(self.campaign.posh_user.username)

                registered = client.register()

                self.campaign.posh_user.is_registered = registered
                self.campaign.posh_user.save()

                if registered:
                    finish_registration_and_list = self.finish_registration(device, list_items, False, client)

                client.driver.press_keycode(3)

            if not (registered and finish_registration_and_list):
                self.campaign.status = Campaign.STOPPED
                self.campaign.save()

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
                registration_finished = client.finish_registration()

                self.campaign.posh_user.finished_registration = registration_finished
                self.campaign.posh_user.save()

                if registration_finished and list_items:
                    listed = self.list_items(device, False, client)

                client.driver.press_keycode(3)
            else:
                with MobilePoshMarkClient(device.serial, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                    client.launch_app(self.campaign.posh_user.username)

                    registration_finished = client.finish_registration()

                    self.campaign.posh_user.finished_registration = registration_finished
                    self.campaign.posh_user.save()

                    if registration_finished and list_items:
                        listed = self.list_items(device, False, client)

                    client.driver.press_keycode(3)

            if not (registration_finished and listed):
                self.campaign.status = Campaign.STOPPED
                self.campaign.save()
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
                    item_listed = client.list_item(item_to_list.listing, listing_images)

                    if item_listed:
                        item_to_list.status = ListedItem.UNDER_REVIEW
                        item_to_list.datetime_listed = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                        item_to_list.save()
            else:
                with MobilePoshMarkClient(device.serial, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                    client.launch_app(self.campaign.posh_user.username)

                    for item_to_list in items_to_list:
                        listing_images = ListingImage.objects.filter(listing=item_to_list.listing)
                        listed = client.list_item(item_to_list.listing, listing_images)

                        if listed:
                            item_to_list.status = ListedItem.UNDER_REVIEW
                            item_to_list.datetime_listed = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                            item_to_list.save()

                            if not item_listed:
                                item_listed = listed

                    client.driver.press_keycode(3)

            if not item_listed:
                self.logger.info('Did not list successfully. Stopping campaign.')

                self.campaign.status = Campaign.STOPPED
                self.campaign.save()
            else:
                all_items = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.UP)

                if all_items.count() == 0:
                    self.campaign.status = Campaign.PAUSED
                    self.campaign.save()

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
                self.campaign.posh_user.save()

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
                                    listed_item.save()
                                listings_can_share.append(listing_title)
                            elif listing_title in all_listings['sold_listings'] and not listed_item.datetime_sold:
                                listed_item.datetime_sold = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                                listed_item.status = ListedItem.SOLD
                                listed_item.save()
                            elif listing_title in all_listings['reserved_listings'] and listed_item.status != ListedItem.RESERVED:
                                listed_item.status = ListedItem.RESERVED
                                listed_item.save()

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
                                listed_item.datetime_sold = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
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
                                now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
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
                        self.campaign.save()

                        return False
                    else:
                        self.logger.info('There are no listings on this user\'s account. Stopping campaign.')

                        self.campaign.status = Campaign.STOPPED
                        self.campaign.save()

                        return False
            else:
                self.logger.info('Stopping campaign because user could not log in')

                self.campaign.status = Campaign.STOPPED
                self.campaign.save()
                return False

    def run(self, campaign_id, logger_id=None, device_id=None, *args, **kwargs):
        self.campaign = Campaign.objects.get(id=campaign_id)
        campaign_delay = None

        self.init_logger(logger_id)

        if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED) and self.campaign.posh_user:
            self.logger.info(f'Campaign, {self.campaign.title}, started for {self.campaign.posh_user.username}')

            try:
                device = Device.objects.get(id=device_id)
            except Device.DoesNotExist:
                device = None

            self.campaign.status = Campaign.RUNNING
            self.campaign.save()

            items_to_list = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED)
            need_to_list = items_to_list.count() > 0

            start_time = time.time()
            try:
                if not (self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package) and device and self.campaign.mode == Campaign.ADVANCED_SHARING:
                    installed = self.install_clone(device)
                elif self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package and device and self.campaign.mode == Campaign.ADVANCED_SHARING:
                    installed = True
                else:
                    installed = False

                if installed and not self.campaign.posh_user.is_registered:
                    success = self.register(device=device, list_items=need_to_list)
                elif installed and not self.campaign.posh_user.finished_registration:
                    success = self.finish_registration(device=device, list_items=need_to_list, reset_ip=True)
                elif installed and items_to_list:
                    success = self.list_items(device)
                elif self.campaign.posh_user.is_registered and self.campaign.mode in (Campaign.ADVANCED_SHARING, Campaign.BASIC_SHARING):
                    success = self.share_and_more()
                else:
                    self.campaign.status = Campaign.STOPPING
                    self.campaign.save()

                    success = False
            except WebDriverException:
                self.logger.error(traceback.format_exc())
                success = False

                if device and self.campaign.mode == Campaign.ADVANCED_SHARING and (not self.campaign.posh_user.is_registered or items_to_list):
                    self.logger.warning('Restarting device and campaign due to a device error')

                    self.campaign.status = Campaign.STARTING
                    self.campaign.save()

                    client = AdbClient(host=os.environ.get('LOCAL_SERVER_IP'), port=5037)
                    adb_device = client.device(serial=device.serial)
                    boot_complete = False

                    adb_device.reboot()

                    device.checkout_time = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                    device.save()

                    while not boot_complete:
                        devices = client.devices()
                        serials = [device.serial for device in devices]

                        if '94TXS0P38' in serials:
                            adb_device = client.device(serial='94TXS0P38')
                            boot_complete = adb_device.shell('getprop sys.boot_completed').strip() == '1'

                        if not boot_complete:
                            self.logger.info('Device not finished rebooting yet. Sleeping for 10 seconds')
                            time.sleep(10)

                    self.logger.info('Reboot complete, starting campaign up again')
                    CampaignTask.delay(campaign_id, logger_id=self.logger.id, device_id=device.id)

                    return None
            except Exception:
                self.logger.error(traceback.format_exc())
                self.logger.error('Stopping campaign due to unhandled error')

                success = False

                self.campaign.status = Campaign.STOPPED
                self.campaign.save()

            end_time = time.time()

            if not self.campaign.posh_user.is_active:
                self.campaign.status = Campaign.STOPPED
                self.campaign.save()

            if not success and self.campaign.status not in (Campaign.STOPPED, Campaign.STOPPING):
                campaign_delay = 3600

            if device:
                self.logger.info('Releasing device')
                device.in_use = False
                device.save()

            if not campaign_delay:
                campaign_delay = self.get_random_delay(end_time - start_time)

            hours, remainder = divmod(campaign_delay, 3600)
            minutes, seconds = divmod(remainder, 60)

            if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED, Campaign.PAUSED):
                self.campaign.status = Campaign.IDLE
                self.campaign.next_runtime = datetime.datetime.utcnow().replace(tzinfo=pytz.utc) + datetime.timedelta(seconds=campaign_delay)
                self.campaign.save()
                self.logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')


CampaignTask = app.register_task(CampaignTask())


@shared_task
def restart_campaigns():
    campaigns = Campaign.objects.filter(status__in=[Campaign.STOPPING, Campaign.IDLE, Campaign.RUNNING])
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

    for campaign in campaigns:
        if campaign.status == Campaign.STOPPING:
            campaign.status = Campaign.STOPPED
            campaign.save()
        elif campaign.next_runtime and campaign.status != Campaign.STOPPING:
            if campaign.next_runtime <= now and campaign.status == Campaign.IDLE:
                campaign.status = Campaign.STARTING
                campaign.save()
                CampaignTask.delay(campaign.id)


@shared_task
def check_posh_users():
    logger = logging.getLogger(__name__)
    logger.info('Checking posh users')
    posh_users = PoshUser.objects.filter(is_active=True, is_registered=True)
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
                                listed_item.datetime_passed_review = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

                                listed_item.status = ListedItem.UP
                                listed_item.save()
                            elif listed_item.status != ListedItem.UNDER_REVIEW and (not campaign or campaign.status not in (Campaign.IDLE, Campaign.RUNNING, Campaign.STARTING)):
                                listed_item.status = ListedItem.UP
                                listed_item.save()

                        elif listing_title in all_listings['sold_listings'] and listed_item.status != ListedItem.SOLD:
                            listed_item.datetime_sold = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                            listed_item.status = ListedItem.SOLD

                            listed_item.save()
                        elif listing_title in all_listings['reserved_listings'] and listed_item.status != ListedItem.RESERVED:
                            listed_item.status = ListedItem.RESERVED
                            listed_item.save()

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
                                listed_item.datetime_sold = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                                listed_item.status = ListedItem.SOLD
                            else:
                                listed_item.status = ListedItem.UP

                            listed_item.save()
                    except ListedItem.MultipleObjectsReturned:
                        pass

                if (all_listings['shareable_listings'] or all_listings['reserved_listings']) and campaign and campaign.status == Campaign.PAUSED:
                    logger.info('User has shareable listings and its campaign is paused. Resuming...')
                    CampaignTask.delay(campaign.id)

            # Checks if the user is inactive when there are no listings and
            if sum([len(y) for y in all_listings.values()]) == 0 and (not campaign or campaign.status not in (Campaign.IDLE, Campaign.RUNNING, Campaign.STARTING)):
                logger.info('User has no listings available...')
                is_active = client.check_inactive(posh_user.username)

                if not is_active:
                    posh_user.is_active = False
                    posh_user.save()

                    if campaign:
                        logger.info('Stopping campaign...')
                        campaign.status = Campaign.STOPPED
                        campaign.save()


@shared_task
def init_campaign(campaign_id, logger_id):
    campaign = Campaign.objects.get(id=campaign_id)
    logger = LogGroup.objects.get(id=logger_id)

    campaign.status = Campaign.STARTING
    campaign.save()
    selected_device = None

    logger.info(f'Getting a device for the following campaign: {campaign}')

    while not selected_device and campaign.status not in (Campaign.STOPPING, Campaign.STOPPED):
        all_devices = Device.objects.filter(is_active=True)
        available_devices = all_devices.filter(in_use=False)

        if available_devices.count() > 0:
            selected_device = available_devices.first()
        else:
            for device in all_devices:
                if (datetime.datetime.utcnow().replace(tzinfo=pytz.utc) - device.checkout_time).seconds >= 900:
                    selected_device = device

                    break

        if selected_device:
            client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
            devices = client.devices()
            serials = [device.serial for device in devices]

            if selected_device.serial not in serials:
                logger.info(f'A connection to the following device could not be made: {selected_device.serial}')
                logger.info('Waiting 10sec')
                selected_device = None
                time.sleep(10)
        else:
            logger.info('No device available, waiting 10sec')
            time.sleep(10)
            campaign.refresh_from_db()

    if campaign.status not in (Campaign.STOPPING, Campaign.STOPPED):
        selected_device.checkout_time = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
        selected_device.in_use = True
        selected_device.save()
        logger.info(f'Device selected: {selected_device}')
        CampaignTask.delay(campaign_id, logger_id=logger.id,device_id=selected_device.id)


@shared_task
def log_cleanup():
    campaigns = Campaign.objects.all()

    for campaign in campaigns:
        logs = LogGroup.objects.filter(campaign=campaign).order_by('-created_date')[5:]

        for log in logs:
            log.delete()
