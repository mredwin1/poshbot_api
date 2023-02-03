import datetime
import logging
import os
import pytz
import random
import requests
import time
import traceback

from celery import shared_task
from ppadb.client import Client as AdbClient
from selenium.common.exceptions import WebDriverException, SessionNotCreatedException

from appium_clients.clients import AppClonerClient, PoshMarkClient as MobilePoshMarkClient
from chrome_clients.clients import PoshMarkClient, BaseClient
from .models import Campaign, Listing, ListingImage, ProxyConnection


def get_proxy(logger):
    try:
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
    except Exception as e:
        logger.debug(f'{traceback.format_exc()}')

        return None


@shared_task
def init_campaign(campaign_id):
    campaign = Campaign.objects.get(id=campaign_id)
    logger = logging.getLogger(__name__)

    campaign_mapping = {
        Campaign.BASIC_SHARING: basic_sharing_campaign,
        Campaign.ADVANCED_SHARING: advanced_sharing_campaign,
        Campaign.BOT_TESTS: bot_tests
    }

    if not campaign.posh_user.is_registered:
        campaign.status = Campaign.STARTING
        campaign.save()
        proxy = None

        logger.info(f'Getting a proxy for the following campaign: {campaign}')

        while not proxy and campaign.status != Campaign.STOPPED:
            proxy = get_proxy(logger)
            if not proxy:
                logger.info('No proxy available, waiting 30sec')
                time.sleep(30)
                campaign.refresh_from_db()

        proxy_connection = ProxyConnection(campaign=campaign,
                                           created_date=datetime.datetime.utcnow().replace(tzinfo=pytz.utc),
                                           proxy_license_uuid=proxy['uuid'], proxy_name=proxy['name'])
        proxy_connection.save()
        logger.info(f'Proxy connection made: {proxy_connection}')

        campaign_mapping[campaign.mode].delay(campaign_id, logger.id, proxy['ip'], proxy['port'])
    else:
        campaign_mapping[campaign.mode].delay(campaign_id, logger.id)


@shared_task
def advanced_sharing_campaign(campaign_id, logger_id=None, proxy_hostname=None, proxy_port=None):
    campaign = Campaign.objects.get(id=campaign_id)
    if campaign.posh_user:
        campaign_listings = Listing.objects.filter(campaign__id=campaign_id)
        delay = campaign.delay * 60
        sign = 1 if random.random() < 0.5 else -1
        deviation = random.randint(0, (delay / 2)) * sign
        register_retries = 0
        update_profile_retries = 0
        listing_shared_retries = 0
        all_listings_retries = 0
        login_retries = 0
        list_item_retries = 0
        registered = campaign.posh_user.is_registered
        profile_updated = campaign.posh_user.profile_updated
        campaign_delay = None
        shared = False
        listing_shared = None
        item_listed = None
        all_listings = None
        logged_in = None

        if logger_id:
            logger = logging.getLogger(__name__)
        else:
            logger = logging.getLogger(__name__)
            # logger.save()

        logger.info(f'Running Advanced Sharing campaign: {campaign}')

        if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active:
            campaign.status = Campaign.RUNNING
            campaign.save()

            start_time = time.time()
            try:
                with PoshMarkClient(campaign, logger, proxy_hostname=proxy_hostname, proxy_port=proxy_port) as client:
                    if registered:
                        client.web_driver.get('https://poshmark.com')
                        client.load_cookies()
                        logged_in = client.check_logged_in()

                        while not logged_in and login_retries < 3:
                            logged_in = client.login(login_retries)
                            login_retries += 1
                    else:
                        while not registered and register_retries < 3:
                            registered = client.register(register_retries)
                            register_retries += 1

                    while not profile_updated and update_profile_retries < 3 and (logged_in or registered):
                        profile_updated = client.update_profile(update_profile_retries)
                        update_profile_retries += 1

                    if profile_updated:
                        campaign.posh_user.profile_updated = True
                        campaign.posh_user.save()

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
                        elif not item_listed:
                            campaign.status = Campaign.STOPPED
                            campaign.save()
                    elif registered:
                        campaign.posh_user.is_registered = True
                        campaign.posh_user.save()

                        for listing in campaign_listings:
                            listing_images = ListingImage.objects.filter(listing=listing)
                            client.list_item(listing, listing_images)
                        campaign_delay = 1800  # Custom delay after list
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
                    advanced_sharing_campaign.apply_async(countdown=campaign_delay, kwargs={'campaign_id': campaign_id})
            except SessionNotCreatedException as e:
                logger.error(f'{traceback.format_exc()}')
                proxy_connection = ProxyConnection.objects.get(campaign=campaign, in_use=True)
                reset_response = proxy_connection.hard_rest()
                logger.warning(reset_response)
                time.sleep(180)
                advanced_sharing_campaign.apply_async(countdown=delay, kwargs={'campaign_id': campaign_id})
            except WebDriverException as e:
                logger.error(f'{traceback.format_exc()}')
                hours, remainder = divmod(delay, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')
                advanced_sharing_campaign.apply_async(countdown=delay, kwargs={'campaign_id': campaign_id})

        if proxy_hostname and proxy_port:
            proxy_connection = ProxyConnection.objects.get(campaign=campaign)
            proxy_connection.in_use = False
            proxy_connection.save()

        if not campaign.posh_user.is_active:
            campaign.status = Campaign.STOPPED
            campaign.save()

        logger.info('Campaign ended')
    else:
        logger = logging.getLogger(__name__)
        logger.error(f'Error while starting {campaign}: No Posh User Assigned')


@shared_task
def basic_sharing_campaign(campaign_id, logger_id=None):
    campaign = Campaign.objects.get(id=campaign_id)
    if campaign.posh_user:
        delay = campaign.delay * 60
        deviation = random.randint(0, (delay / 2))
        shared = False
        campaign_delay = None
        login_retries = 0

        if logger_id:
            logger = logging.getLogger(__name__)
        else:
            logger = logging.getLogger(__name__)
            # logger.save()

        logger.info(f'Running Basic Sharing campaign: {campaign})')

        if campaign.status != Campaign.STOPPED and campaign.posh_user.is_active and campaign.posh_user.is_registered:
            campaign.status = Campaign.RUNNING
            campaign.save()

            start_time = time.time()

            try:
                with PoshMarkClient(campaign, logger) as client:
                    client.web_driver.get('https://poshmark.com')
                    client.load_cookies()
                    logged_in = client.check_logged_in()

                    while not logged_in and login_retries < 3:
                        logged_in = client.login(login_retries)
                        login_retries += 1

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
            except SessionNotCreatedException as e:
                logger.error(f'{traceback.format_exc()}')
                proxy_connection = ProxyConnection.objects.get(campaign=campaign, in_use=True)
                reset_response = proxy_connection.hard_rest()
                logger.warning(reset_response)
                time.sleep(180)
                advanced_sharing_campaign.apply_async(countdown=delay, kwargs={'campaign_id': campaign_id})
            except WebDriverException as e:
                logger.error(f'{traceback.format_exc()}')
                hours, remainder = divmod(delay, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.info(
                    f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')
                advanced_sharing_campaign.apply_async(countdown=delay, kwargs={'campaign_id': campaign_id})

        if not campaign.posh_user.is_active or not campaign.posh_user.is_registered:
            campaign.status = Campaign.STOPPED
            campaign.save()

        logger.info('Campaign ended')
    else:
        logger = logging.getLogger(__name__)
        logger.error(f'Error while starting {campaign}: No Posh User Assigned')


@shared_task
def bot_tests(campaign_id, logger_id, proxy_hostname=None, proxy_port=None):
    campaign = Campaign.objects.get(id=campaign_id)
    logger = logging.getLogger(__name__)

    campaign.status = Campaign.RUNNING
    campaign.save()
    logger.info(f'Running Bot Test Campaign: {campaign.title}')

    with BaseClient(logger, proxy_ip=proxy_hostname, proxy_port=proxy_port) as client:
        client.bot_check()

    if proxy_hostname and proxy_port:
        proxy_connection = ProxyConnection.objects.get(campaign=campaign, in_use=True)
        proxy_connection.in_use = False
        proxy_connection.save()

    campaign.status = Campaign.STOPPED
    campaign.save()

    logger.info('Campaign ended')


@shared_task
def register(campaign_id):
    campaign = Campaign.objects.get(id=campaign_id)
    campaign_listings = Listing.objects.filter(campaign__id=campaign_id)
    logger = logging.getLogger(__name__)

    campaign.status = Campaign.RUNNING
    campaign.save()

    response = requests.get('https://portal.mobilehop.com/proxies/7334080c0e9b4dd086c2fd037b3a6df4/reset')
    logger.info(response.text)

    try:
        with AppClonerClient(logger, campaign.posh_user.username) as client:
            client.add_clone()
            client.launch_clone()
            clone_app_package = client.get_current_app_package()

        with MobilePoshMarkClient(campaign, logger, clone_app_package) as client:
            client.register()

            for listing_not_listed in campaign_listings:
                listing_images = ListingImage.objects.filter(listing=listing_not_listed)
                client.list_item(listing_not_listed, listing_images)

        client = AdbClient(host=os.environ.get('LOCAL_SERVER_IP'), port=5037)
        device = client.device(serial='94TXS0P38')
        device.shell('am force-stop com.applisto.appcloner')
        device.shell(f'am force-stop {clone_app_package}')

    except (TimeoutError, WebDriverException):
        logger = logging.getLogger(__name__)
        logger.error(f'{traceback.format_exc()}')

    campaign.status = Campaign.STOPPED
    campaign.save()
