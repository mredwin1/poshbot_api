from time import sleep
from celery import shared_task


@shared_task
def advanced_sharing_campaign(campaign_id):
    print(f'Running Advanced Sharing campaign (Campaign ID: {campaign_id})')
    sleep(10)
    print('Campaign ended')
