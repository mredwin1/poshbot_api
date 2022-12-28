import datetime
import logging
import random
import requests
import time
import traceback

from celery import shared_task
from chrome_clients.clients import PoshMarkClient
from selenium.common.exceptions import WebDriverException

from .models import Campaign, Listing, ListingImage

logger = logging.getLogger(__name__)


@shared_task
def advanced_sharing_campaign(campaign_id):
    print(f'Running Advanced Sharing campaign (Campaign ID: {campaign_id})')
    campaign = Campaign.objects.get(id=campaign_id)
    campaign_listings = Listing.objects.filter(campaign__id=campaign_id)
    delay = campaign.delay * 60
    sign = 1 if random.random() < 0.5 else -1
    deviation = random.randint(0, (delay / 2)) * sign
    register_retries = 0
    campaign_delay = None

    if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
        campaign.status = Campaign.RUNNING
        campaign.save()

        start_time = time.time()
        try:
            with PoshMarkClient(campaign, logger, proxy_hostname='192.154.244.85', proxy_port='8000') as client:
                while not campaign.posh_user.is_registered and not campaign.posh_user.profile_updated and campaign.posh_user.is_active and register_retries < 3:
                    client.register()
                    campaign.refresh_from_db()
                    register_retries += 1

                if campaign.posh_user.is_registered and campaign.posh_user.is_active:
                    if not campaign.posh_user.profile_updated:
                        client.update_profile()
                    all_listings = client.get_all_listings()
                    all_listing_titles = []

                    if all_listings:
                        shared = False
                        for listings in all_listings.values():
                            all_listing_titles += listings

                        for listing in campaign_listings:
                            if listing.title not in all_listing_titles:
                                listing_images = ListingImage.objects.filter(listing=listing)
                                client.list_item(listing, listing_images)
                                campaign_delay = 1800  # Custom delay after list
                            elif listing.title in all_listings['shareable_listings']:
                                listing_shared = client.share_item(listing.title)

                                if not shared:
                                    shared = listing_shared

                        if random.random() < .10 and shared:
                            today = datetime.datetime.today()
                            nine_pm = datetime.datetime(year=today.year, month=today.month, day=(today.day + 1), hour=2,
                                                        minute=0, second=0)
                            midnight = datetime.datetime(year=today.year, month=today.month, day=(today.day + 1), hour=5,
                                                         minute=0, second=0)
                            if nine_pm < today < midnight:
                                client.send_offer_to_likers(listing.title)

                        if random.random() < .20 and shared:
                            client.check_offers(listing.title)

                        if not shared and not campaign_delay:
                            campaign_delay = 3600
                    else:
                        campaign.status = Campaign.STOPPED
                        campaign.save()

            campaign.refresh_from_db()
            response = requests.get('https://portal.mobilehop.com/proxies/b6e8b8a1f38f4ba3937aa83f6758903a/reset')
            logger.info(response.text)
            time.sleep(10)

            if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
                if not campaign_delay:
                    end_time = time.time()
                    elapsed_time = round(end_time - start_time, 2)
                    campaign_delay = (delay - elapsed_time) + deviation if elapsed_time > 1 else deviation

                campaign.status = Campaign.IDLE
                campaign.save()
                hours, remainder = divmod(campaign_delay, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')
                advanced_sharing_campaign.apply_async(countdown=campaign_delay, kwargs={'campaign_id': campaign_id})
        except WebDriverException as e:
            logger.error(f'{traceback.format_exc()}')
            response = requests.get('https://portal.mobilehop.com/api/v1/modems/reset/832aeef52d6f4ce59dad8d3b6dcf6868')
            logger.info(response.text)
            time.sleep(180)

    print('Campaign ended')


@shared_task
def basic_sharing_campaign(campaign_id):
    print(f'Running Basic Sharing campaign (Campaign ID: {campaign_id})')
    campaign = Campaign.objects.get(id=campaign_id)
    delay = campaign.delay * 60
    deviation = random.randint(0, (delay / 2))

    if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
        campaign.status = Campaign.RUNNING
        campaign.save()

        start_time = time.time()

        try:
            if campaign.posh_user.is_registered:
                with PoshMarkClient(campaign, logger, proxy_hostname='192.154.244.85', proxy_port='8000') as client:
                    all_listings = client.get_all_listings()

                    if all_listings:
                        for listing_title in all_listings['shareable_listings']:
                            client.share_item(listing_title)

                            today = datetime.datetime.today()
                            nine_pm = datetime.datetime(year=today.year, month=today.month, day=(today.day + 1), hour=2,
                                                        minute=0,
                                                        second=0)
                            if today > nine_pm:
                                client.send_offer_to_likers(listing_title)

                            client.check_offers(listing_title)

            response = requests.get('https://portal.mobilehop.com/proxies/b6e8b8a1f38f4ba3937aa83f6758903a/reset')
            logger.info(response.text)
            time.sleep(10)

            end_time = time.time()
            elapsed_time = round(end_time - start_time, 2)
            campaign_delay = (delay - elapsed_time) + deviation if elapsed_time > 1 else deviation

            campaign.refresh_from_db()
            if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
                campaign.status = Campaign.IDLE
                campaign.save()
                hours, remainder = divmod(campaign_delay, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(
                    f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')
                basic_sharing_campaign.apply_async(countdown=campaign_delay, kwargs={'campaign_id': campaign_id})
        except WebDriverException as e:
            logger.error(f'{traceback.format_exc()}')
            response = requests.get(
                'https://portal.mobilehop.com/api/v1/modems/reset/832aeef52d6f4ce59dad8d3b6dcf6868')
            logger.info(response.text)
            time.sleep(180)

    print('Campaign ended')
