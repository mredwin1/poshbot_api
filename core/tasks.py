import datetime
import logging
import pytz
import random
import requests
import time
import traceback

from celery import shared_task, Task
from selenium.common.exceptions import WebDriverException

from appium_clients.clients import AppClonerClient, PoshMarkClient as MobilePoshMarkClient
from chrome_clients.clients import PoshMarkClient, PublicPoshMarkClient
from poshbot_api.celery import app
from .models import Campaign, Listing, ListingImage, PoshUser, Device, LogGroup, ListedItem


class CampaignTask(Task):
    def __init__(self):
        self.campaign = None
        self.logger = None

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

    def register(self, list_items, device):
        ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            try:
                with AppClonerClient(device.serial, self.logger, self.campaign.posh_user.username) as client:
                    client.add_clone()
                    client.launch_app(self.campaign.posh_user.username)

                    time.sleep(4)

                    clone_app_package = client.get_current_app_package()

                self.campaign.posh_user.app_package = clone_app_package
                self.campaign.posh_user.device = device
                self.campaign.posh_user.save()

                with MobilePoshMarkClient(device.serial, self.campaign, self.logger, clone_app_package) as client:
                    registered = client.register()

                    if registered and list_items:
                        listed = self.list_items(device, False, client)

                    client.driver.press_keycode(3)

                if not (registered and listed):
                    self.campaign.status = Campaign.STOPPED
                    self.campaign.save()
                    return False

                self.campaign.status = Campaign.PAUSED
                self.campaign.save()
                return True

            except (TimeoutError, WebDriverException):
                self.logger.error(traceback.format_exc())
                self.campaign.status = Campaign.STOPPED
                self.campaign.save()

                return False

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
                    listings = all_listings['shareable_listings'] + all_listings['sold_listings'] + all_listings['reserved_listings']
                    listed_items = ListedItem.objects.filter(posh_user=self.campaign.posh_user)
                    now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

                    for listed_item in listed_items:
                        if not listed_item.datetime_passed_review and listed_item.listing.title in listings:
                            listed_item.datetime_passed_review = now
                            listed_item.status = ListedItem.UP

                        if not listed_item.datetime_sold and listed_item.listing.title in all_listings['sold_listings']:
                            listed_item.datetime_passed_review = now
                            listed_item.status = ListedItem.SOLD

                        if listed_item.listing.title in all_listings['reserved_listings']:
                            listed_item.status = ListedItem.RESERVED

                        if listed_item.listing.title not in listings:
                            listed_item.datetime_removed = now
                            listed_item.status = ListedItem.REMOVED

                        listed_item.save()

                    if all_listings['shareable_listings']:
                        for listing_title in all_listings['shareable_listings']:
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

                        if not shared:
                            return False

                        return True

                    elif all_listings['reserved_listings']:
                        return False
                    else:
                        self.campaign.status = Campaign.STOPPED
                        self.campaign.save()

                        return False


            else:
                self.campaign.status = Campaign.STOPPED
                self.campaign.save()
                return False

    def run(self, campaign_id, logger_id=None, device_id=None, *args, **kwargs):
        self.campaign = Campaign.objects.get(id=campaign_id)
        success = False
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

            start_time = time.time()
            if not self.campaign.posh_user.is_registered and self.campaign.mode == Campaign.ADVANCED_SHARING and device:
                success = self.register(list_items=True, device=device)
            elif self.campaign.posh_user.is_registered and items_to_list and device:
                success = self.list_items(device)
            elif self.campaign.posh_user.is_registered and self.campaign.mode in (Campaign.ADVANCED_SHARING, Campaign.BASIC_SHARING):
                success = self.share_and_more()
            else:
                self.campaign.status = Campaign.STOPPING
                self.campaign.save()

                success = False
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

            self.campaign.refresh_from_db()

            if not campaign_delay:
                delay = self.campaign.delay * 60
                sign = 1 if random.random() < 0.5 else -1
                deviation = random.randint(0, (delay / 2)) * sign
                elapsed_time = round(end_time - start_time, 2)
                campaign_delay = (delay - elapsed_time) + deviation if (delay - elapsed_time) + deviation > 1 else random.randint(0, (delay / 2))

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

            if not campaign or campaign.status not in (Campaign.RUNNING, Campaign.IDLE, Campaign.STARTING):
                all_listings = client.get_all_listings(posh_user.username)

                if sum([len(y) for y in all_listings.values()]) == 0:
                    logger.info('User has no listings available...')
                    is_active = client.check_inactive(posh_user.username)

                    if not is_active:
                        posh_user.is_active = False
                        posh_user.save()

                        if campaign:
                            logger.info('Stopping campaign...')
                            campaign.status = Campaign.STOPPED
                            campaign.save()

                elif (all_listings['shareable_listings'] or all_listings['sold_listings'] or all_listings['reserved_listings']) and campaign and campaign.status == Campaign.PAUSED:
                    listings = all_listings['shareable_listings'] + all_listings['sold_listings'] + all_listings['reserved_listings']

                    for listing in listings:
                        try:
                            listed_item = ListedItem.objects.get(posh_user=campaign.posh_user, listing__title=listing)

                            if not listed_item.datetime_passed_review:
                                listed_item.datetime_passed_review = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                                listed_item.status = ListedItem.UP

                            if not listed_item.datetime_sold and listing in all_listings['sold_listings']:
                                listed_item.datetime_passed_review = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                                listed_item.status = ListedItem.SOLD

                            listed_item.save()

                        except ListedItem.DoesNotExist:
                            logger.warning(f'Could not find a listed item for {campaign.posh_user} with title {listing}')

                    logger.info('User has shareable listings and its campaign is paused. Resuming...')
                    CampaignTask.delay(campaign.id)


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

        if not selected_device:
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
