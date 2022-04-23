from time import sleep
from celery import shared_task
from .models import Campaign


@shared_task
def advanced_sharing_campaign(campaign_id):
    print(f'Running Advanced Sharing campaign (Campaign ID: {campaign_id})')
    campaign = Campaign.objects.get(id=campaign_id)
    campaign.status = Campaign.RUNNING
    campaign.save()
    sleep(campaign.delay)
    print('Campaign ended')
