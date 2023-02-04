import datetime
import logging
import pytz
import random
import requests
import time

from celery import shared_task, Task
from selenium.common.exceptions import WebDriverException

from appium_clients.clients import AppClonerClient, PoshMarkClient as MobilePoshMarkClient
from chrome_clients.clients import PoshMarkClient
from poshbot_api.celery import app
from .models import Campaign, Listing, ListingImage


class CampaignTask(Task):
    def __init__(self):
        self.campaign = None
        self.logger = None

    def init_logger(self, logger_id=None):
        if logger_id:
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = logging.getLogger(__name__)

    def update_status(self, status):
        self.campaign.status = status
        self.campaign.save()

    def disable_posh_ser(self):
        self.campaign.posh_user.is_active = False
        self.campaign.posh_user.save()

    def register(self, list_items):
        response = requests.get('https://portal.mobilehop.com/proxies/7334080c0e9b4dd086c2fd037b3a6df4/reset')
        self.logger.info(response.text)

        try:
            with AppClonerClient(self.logger, self.campaign.posh_user.username) as client:
                client.add_clone()
                client.launch_clone()
                clone_app_package = client.get_current_app_package()

            with MobilePoshMarkClient(self.campaign, self.logger, clone_app_package) as client:
                client.register()

                if list_items:
                    campaign_listings = Listing.objects.filter(campaign__id=self.campaign.id)
                    for listing_not_listed in campaign_listings:
                        listing_images = ListingImage.objects.filter(listing=listing_not_listed)
                        client.list_item(listing_not_listed, listing_images)

                client.driver.press_keycode(3)

            self.update_status(Campaign.PAUSED)
            return True

        except (TimeoutError, WebDriverException) as e:
            self.logger.error(e, exc_info=True)
            self.update_status(Campaign.STOPPED)

            return False

    def share_and_more(self):
        login_retries = 0
        update_profile_retries = 0
        all_listings_retries = 0
        listing_shared_retries = 0
        profile_updated = self.campaign.posh_user.profile_updated
        campaign_delay = None
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

                # all_available_listings = []
                # if all_listings:
                #     for listings in all_listings.values():
                #         all_available_listings += listings
                #
                # listings_not_listed = [listing for listing in campaign_listings if
                #                        listing.title not in all_available_listings]
                #
                # for listing_not_listed in listings_not_listed:
                #     listing_images = ListingImage.objects.filter(listing=listing_not_listed)
                #     while item_listed is None and list_item_retries < 3:
                #         item_listed = client.list_item(listing_not_listed, listing_images, list_item_retries)
                #         list_item_retries += 1

                if all_listings:
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

                        if not shared and not campaign_delay:
                            return False

                        return True

                    elif all_listings['reserved_listings']:
                        return False
                    else:
                        self.update_status(Campaign.STOPPED)

                        return False
            else:
                self.update_status(Campaign.STOPPED)
                return False

    def run(self, campaign_id, logger_id=None, *args, **kwargs):
        self.campaign = Campaign.objects.get(id=campaign_id)
        success = False
        campaign_delay = None

        self.init_logger(logger_id)

        if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED) and self.campaign.posh_user:
            self.logger.info(f'Campaign, {self.campaign.title}, started for {self.campaign.posh_user.username}')

            self.update_status(Campaign.RUNNING)

            start_time = time.time()
            if not self.campaign.posh_user.is_registered and self.campaign.mode == Campaign.ADVANCED_SHARING:
                success = self.register(list_items=True)
            elif not self.campaign.posh_user.is_registered and self.campaign.mode != Campaign.ADVANCED_SHARING:
                self.disable_posh_user()
                self.update_status(Campaign.STOPPING)

                success = False

            elif self.campaign.posh_user.is_registered and self.campaign.mode in (Campaign.ADVANCED_SHARING, Campaign.BASIC_SHARING):
                success = self.share_and_more()
            end_time = time.time()

            if not success and self.campaign.status not in (Campaign.STOPPED, Campaign.STOPPING):
                campaign_delay = 3600
            elif not success and self.campaign.status in (Campaign.STOPPED, Campaign.STOPPING):
                if self.campaign.status != Campaign.STOPPED:
                    self.update_status(Campaign.STOPPED)

                return None

            if not campaign_delay:
                delay = self.campaign.delay * 60
                sign = 1 if random.random() < 0.5 else -1
                deviation = random.randint(0, (delay / 2)) * sign
                elapsed_time = round(end_time - start_time, 2)
                campaign_delay = (delay - elapsed_time) + deviation if (delay - elapsed_time) > 1 else deviation

            hours, remainder = divmod(campaign_delay, 3600)
            minutes, seconds = divmod(remainder, 60)

            if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED):
                self.update_status(Campaign.IDLE)
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
        else:
            if campaign.next_runtime <= now and campaign.status == Campaign.IDLE:
                CampaignTask.delay(campaign.id)
            elif (campaign.next_runtime + datetime.timedelta(minutes=10)) <= now and campaign.status == Campaign.RUNNING:
                campaign.status = Campaign.STOPPED
                campaign.save()

# @shared_task
# def init_campaign(campaign_id):
#     campaign = Campaign.objects.get(id=campaign_id)
#     logger = logging.getLogger(__name__)
#
#     campaign_mapping = {
#         Campaign.BASIC_SHARING: basic_sharing_campaign,
#         Campaign.ADVANCED_SHARING: advanced_sharing_campaign,
#         Campaign.BOT_TESTS: bot_tests
#     }
#
#     if not campaign.posh_user.is_registered:
#         campaign.status = Campaign.STARTING
#         campaign.save()
#         proxy = None
#
#         logger.info(f'Getting a proxy for the following campaign: {campaign}')
#
#         while not proxy and campaign.status != Campaign.STOPPED:
#             proxy = get_proxy(logger)
#             if not proxy:
#                 logger.info('No proxy available, waiting 30sec')
#                 time.sleep(30)
#                 campaign.refresh_from_db()
#
#         proxy_connection = ProxyConnection(campaign=campaign,
#                                            created_date=datetime.datetime.utcnow().replace(tzinfo=pytz.utc),
#                                            proxy_license_uuid=proxy['uuid'], proxy_name=proxy['name'])
#         proxy_connection.save()
#         logger.info(f'Proxy connection made: {proxy_connection}')
#
#         campaign_mapping[campaign.mode].delay(campaign_id, logger.id, proxy['ip'], proxy['port'])
#     else:
#         campaign_mapping[campaign.mode].delay(campaign_id, logger.id)
