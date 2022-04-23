from time import sleep
from celery import shared_task
from .models import Campaign


@shared_task
def advanced_sharing_campaign(campaign_id):
    print(f'Running Advanced Sharing campaign (Campaign ID: {campaign_id})')
    campaign = Campaign.objects.get(id=campaign_id)
    campaign.status = Campaign.RUNNING
    campaign.save()

    sleep(120)

    if campaign.status != Campaign.STOPPED:
        campaign.status = Campaign.IDLE
        campaign.save()
        advanced_sharing_campaign.apply_async(countdown=5, kwargs={'campaign_id': campaign_id})
    print('Campaign ended')
