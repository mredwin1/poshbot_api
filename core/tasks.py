import logging
from celery import shared_task
from chrome_clients.clients import PoshMarkClient

from .models import Campaign

logger = logging.getLogger(__name__)


@shared_task
def advanced_sharing_campaign(campaign_id):
    print(f'Running Advanced Sharing campaign (Campaign ID: {campaign_id})')
    campaign = Campaign.objects.get(id=campaign_id)
    if campaign.status != Campaign.STOPPED:
        campaign.status = Campaign.RUNNING
        campaign.save()

        with PoshMarkClient(campaign, logger) as client:
            client.register()

        campaign.refresh_from_db()
        if campaign.status != Campaign.STOPPED:
            campaign.status = Campaign.IDLE
            campaign.save()
            advanced_sharing_campaign.apply_async(countdown=5, kwargs={'campaign_id': campaign_id})
    print('Campaign ended')
