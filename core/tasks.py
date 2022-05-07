import logging
import random
import time

from celery import shared_task
from chrome_clients.clients import PoshMarkClient

from .models import Campaign, Listing

logger = logging.getLogger(__name__)


@shared_task
def advanced_sharing_campaign(campaign_id):
    print(f'Running Advanced Sharing campaign (Campaign ID: {campaign_id})')
    campaign = Campaign.objects.get(id=campaign_id)
    listings = Listing.objects.filter(campaign=campaign)
    delay = campaign.delay * 60
    deviation = random.randint(0, (delay / 2))
    register_retries = 0

    if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
        campaign.status = Campaign.RUNNING
        campaign.save()

        start_time = time.time()

        while not campaign.posh_user.is_registered and not campaign.posh_user.profile_updated and register_retries < 3:
            with PoshMarkClient(campaign, logger, '192.154.246.207', '8000') as client:
                client.register()
            register_retries += 1

            campaign.refresh_from_db()
            if not campaign.posh_user.is_registered and not campaign.posh_user.profile_updated and register_retries < 3:
                logger.info('Retrying registration and profile update in 5 seconds')
                time.sleep(5)

        if campaign.posh_user.is_registered:
            with PoshMarkClient(campaign, logger) as client:
                all_listings = client.get_all_listings()
                all_listing_titles = []

                for listings in all_listings.values():
                    all_listing_titles += listings

                logger.info(f'All listing titles: {all_listing_titles}')
                logger.info(f'All listings: {listings}')

                for listing in listings:
                    if listing not in all_listings:
                        client.list_item(listing)

                for shareable_listing in all_listings['shareable_listings']:
                    client.share_item(shareable_listing)

        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        campaign_delay = (delay - elapsed_time) - deviation

        campaign.refresh_from_db()
        if campaign.status != Campaign.STOPPED:
            campaign.status = Campaign.IDLE
            campaign.save()
            hours, remainder = divmod(campaign_delay, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')
            advanced_sharing_campaign.apply_async(countdown=campaign_delay, kwargs={'campaign_id': campaign_id})

    print('Campaign ended')
