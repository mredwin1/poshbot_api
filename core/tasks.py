import datetime
import os
import pytz
import random
import requests
import time
import traceback

from celery import shared_task
from chrome_clients.clients import PoshMarkClient
from selenium.common.exceptions import WebDriverException

from .models import Campaign, Listing, ListingImage, ProxyConnection, LogGroup


def get_proxy(logger):
    cookies = ProxyConnection.authenticate()
    list_response = requests.get('https://portal.mobilehop.com/api/v2/proxies/list', cookies=cookies)

    available_proxies = list_response.json()['result']

    for available_proxy in available_proxies:
        connections = ProxyConnection.objects.filter(proxy_license_uuid=available_proxy['uuid'])
        connections_in_use = connections.filter(in_use=True)
        if connections.count() >= int(os.environ.get('MAX_PROXY_CONNECTIONS', '1')) and connections_in_use.count() == 0:
            first_connection = connections.first()
            reset_response = first_connection.fast_reset()

            logger.info(reset_response)
            time.sleep(10)

            connections.delete()
            return available_proxy
        elif connections.count() < int(os.environ.get('MAX_PROXY_CONNECTIONS', '1')):
            return available_proxy
        else:
            for connection in connections:
                if (datetime.datetime.utcnow().replace(tzinfo=pytz.utc) - connection.created_date).seconds > 900:
                    connection.delete()
                    return available_proxy

    return None


@shared_task
def init_campaign(campaign_id, logger_id):
    campaign = Campaign.objects.get(id=campaign_id)
    logger = LogGroup.objects.get(id=logger_id)

    if not campaign.posh_user.is_registered:
        proxy = None

        logger.info(f'Getting a proxy for the following campaign: {campaign}')

        while not proxy:
            proxy = get_proxy(logger)
            if not proxy:
                logger.info('No proxy available, waiting 30sec')
                time.sleep(30)

        proxy_connection = ProxyConnection(campaign=campaign, created_date=datetime.datetime.utcnow().replace(tzinfo=pytz.utc), proxy_license_uuid=proxy['uuid'], proxy_name=proxy['name'])
        proxy_connection.save()
        logger.info(f'Proxy connection made: {proxy_connection}')

        advanced_sharing_campaign.delay(campaign_id, logger_id, proxy['ip'], proxy['port'])
    else:
        advanced_sharing_campaign.delay(campaign_id, logger_id)


@shared_task
def advanced_sharing_campaign(campaign_id, logger_id=None, proxy_hostname=None, proxy_port=None):
    campaign = Campaign.objects.get(id=campaign_id)
    campaign_listings = Listing.objects.filter(campaign__id=campaign_id)
    delay = campaign.delay * 60
    sign = 1 if random.random() < 0.5 else -1
    deviation = random.randint(0, (delay / 2)) * sign
    register_retries = 0
    campaign_delay = None
    shared = False
    is_new_user = not campaign.posh_user.is_registered

    if logger_id:
        logger = LogGroup.objects.get(id=logger_id)
    else:
        logger = LogGroup(campaign=campaign, posh_user=campaign.posh_user)
        logger.save()

    logger.info(f'Running Advanced Sharing campaign: {campaign}')

    if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
        campaign.status = Campaign.RUNNING
        campaign.save()

        start_time = time.time()
        try:
            with PoshMarkClient(campaign, logger, proxy_hostname=proxy_hostname, proxy_port=proxy_port) as client:
                while not campaign.posh_user.is_registered and not campaign.posh_user.profile_updated and campaign.posh_user.is_active and register_retries < 3:
                    client.register()
                    campaign.refresh_from_db()
                    register_retries += 1

                if campaign.posh_user.is_registered and campaign.posh_user.is_active:
                    if not campaign.posh_user.profile_updated:
                        client.update_profile()

                    if is_new_user:
                        for listing in campaign_listings:
                            listing_images = ListingImage.objects.filter(listing=listing)
                            client.list_item(listing, listing_images)
                        campaign_delay = 1800  # Custom delay after list
                    else:
                        all_listings = client.get_all_listings()

                        if all_listings:
                            all_available_listings = []

                            for listings in all_listings.values():
                                all_available_listings += listings

                            listings_not_listed = [listing for listing in campaign_listings if listing.title not in all_available_listings]

                            for listing_not_listed in listings_not_listed:
                                listing_images = ListingImage.objects.filter(listing=listing_not_listed)
                                client.list_item(listing_not_listed, listing_images)

                            if all_listings['shareable_listings']:
                                for listing_title in all_listings['shareable_listings']:
                                    listing_shared = client.share_item(listing_title)

                                    if not shared:
                                        shared = listing_shared

                                if random.random() < .20 and shared:
                                    logger.info('Seeing if it is time to send offers to likers')
                                    now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                                    nine_pm = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=2,
                                                                minute=0, second=0).replace(tzinfo=pytz.utc)
                                    midnight = nine_pm + datetime.timedelta(hours=3)

                                    if nine_pm < now < midnight:
                                        client.send_offer_to_likers(listing_title)
                                    else:
                                        logger.info(f"Not the time to send offers to likers. Current Time: {now.astimezone(pytz.timezone('US/Eastern')).strftime('%I:%M %p')} Eastern")

                                if random.random() < .20 and shared:
                                    client.check_offers(listing_title)

                                if not shared and not campaign_delay:
                                    campaign_delay = 3600
                            elif all_listings['reserved_listings']:
                                campaign_delay = 3600
                            elif not listings_not_listed:
                                campaign.status = Campaign.STOPPED
                                campaign.save()
                        else:
                            campaign_delay = 30

            if proxy_hostname and proxy_port:
                proxy_connection = ProxyConnection.objects.get(campaign=campaign)
                proxy_connection.in_use = False
                proxy_connection.save()

            campaign.refresh_from_db()

            if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
                if not campaign_delay:
                    end_time = time.time()
                    elapsed_time = round(end_time - start_time, 2)
                    campaign_delay = (delay - elapsed_time) + deviation if (delay - elapsed_time) > 1 else deviation

                campaign.status = Campaign.IDLE
                campaign.save()
                hours, remainder = divmod(campaign_delay, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')
                advanced_sharing_campaign.apply_async(countdown=campaign_delay, kwargs={'campaign_id': campaign_id})
        except WebDriverException as e:
            logger.error(f'{traceback.format_exc()}')
            proxy_connection = ProxyConnection.objects.get(campaign=campaign)
            proxy_connection.hard_rest()
            time.sleep(180)

    if not campaign.posh_user.is_active:
        campaign.status = Campaign.STOPPED
        campaign.save()

    logger.info('Campaign ended')


@shared_task
def basic_sharing_campaign(campaign_id, logger_id=None):
    campaign = Campaign.objects.get(id=campaign_id)
    delay = campaign.delay * 60
    deviation = random.randint(0, (delay / 2))
    shared = False
    campaign_delay = None

    if logger_id:
        logger = LogGroup.objects.get(id=logger_id)
    else:
        logger = LogGroup(campaign=campaign, posh_user=campaign.posh_user)
        logger.save()

    logger.info(f'Running Basic Sharing campaign: {campaign})')

    if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active and campaign.posh_user.is_registered:
        campaign.status = Campaign.RUNNING
        campaign.save()

        start_time = time.time()

        try:
            with PoshMarkClient(campaign, logger) as client:
                all_listings = client.get_all_listings()

                if all_listings['shareable_listings']:
                    for listing_title in all_listings['shareable_listings']:
                        listing_shared = client.share_item(listing_title)

                        if not shared:
                            shared = listing_shared

                    if random.random() < .50 and shared:
                        logger.info('Seeing if it is time to send offers to likers')
                        now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                        nine_pm = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=2,
                                                            minute=0, second=0).replace(tzinfo=pytz.utc)
                        midnight = nine_pm + datetime.timedelta(hours=3)

                        if nine_pm < now < midnight:
                            client.send_offer_to_likers(listing_title)
                        else:
                            logger.info(f"Not the time to send offers to likers. Current Time: {now.astimezone(pytz.timezone('US/Eastern')).strftime('%I:%M %p')} Eastern")

                    if random.random() < .20 and shared:
                        client.check_offers(listing_title)

                    if not shared and not campaign_delay:
                        campaign_delay = 3600
                elif all_listings['reserved_listings']:
                    campaign_delay = 3600
                else:
                    campaign.status = Campaign.STOPPED
                    campaign.save()

            campaign.refresh_from_db()
            if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
                if not campaign_delay:
                    end_time = time.time()
                    elapsed_time = round(end_time - start_time, 2)
                    campaign_delay = (delay - elapsed_time) + deviation if (delay - elapsed_time) > 1 else deviation

                campaign.status = Campaign.IDLE
                campaign.save()
                hours, remainder = divmod(campaign_delay, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')
                basic_sharing_campaign.apply_async(countdown=campaign_delay, kwargs={'campaign_id': campaign_id})
        except WebDriverException as e:
            logger.error(f'{traceback.format_exc()}')

    if not campaign.posh_user.is_active or not campaign.posh_user.is_registered:
        campaign.status = Campaign.STOPPED
        campaign.save()

    logger.info('Campaign ended')
