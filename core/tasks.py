import logging
import random
import time

from celery import shared_task
from chrome_clients.clients import PoshMarkClient

from .models import Campaign

logger = logging.getLogger(__name__)


@shared_task
def advanced_sharing_campaign(campaign_id):
    print(f'Running Advanced Sharing campaign (Campaign ID: {campaign_id})')
    campaign = Campaign.objects.get(id=campaign_id)
    delay = campaign.delay * 60
    positive_negative = 1 if random.random() < 0.5 else -1
    deviation = random.randint(0, (delay / 2)) * positive_negative

    if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
        campaign.status = Campaign.RUNNING
        campaign.save()

        start_time = time.time()
        with PoshMarkClient(campaign, logger, '192.154.246.219', '8000') as client:
            client.register()

        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        campaign_delay = (delay - elapsed_time) + deviation

        campaign.refresh_from_db()
        if campaign.status != Campaign.STOPPED:
            campaign.status = Campaign.IDLE
            campaign.save()
            hours, remainder = divmod(campaign_delay, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.info(f'Campaign will start back up in {hours} hours {minutes} minutes and {round(seconds)} seconds')
            advanced_sharing_campaign.apply_async(countdown=campaign_delay, kwargs={'campaign_id': campaign_id})
    print('Campaign ended')
