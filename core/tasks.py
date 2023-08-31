import datetime
import logging
import os
import pytz
import random
import requests
import smtplib
import time
import traceback

from celery import shared_task, Task
from celery.exceptions import TimeLimitExceeded, SoftTimeLimitExceeded
from django.db.models import Q
from django.utils import timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from ppadb.client import Client as AdbClient
from selenium.common.exceptions import WebDriverException

from appium_clients.clients import AppClonerClient, PoshMarkClient as MobilePoshMarkClient
from chrome_clients.clients import PoshMarkClient, PublicPoshMarkClient
from email_retrieval import zke_yahoo
from poshbot_api.celery import app
from .models import Campaign, Listing, ListingImage, PoshUser, Device, LogGroup, ListedItem, ListedItemToReport, ListedItemReport, PaymentEmailContent


class CampaignTask(Task):
    def __init__(self):
        self.soft_time_limit = 900
        self.time_limit = 1200
        self.campaign = None
        self.logger = None
        self.device = None

    def get_random_delay(self, elapsed_time):
        delay = self.campaign.delay * 60

        if delay <= 0:
            return 0
        else:
            range_start = max(0, delay - (delay * 0.3))
            range_end = delay + (delay * 0.3)
            random_delay_in_seconds = round(random.uniform(range_start, range_end))
            delay_after_elapsed_time_in_seconds = random_delay_in_seconds - elapsed_time
            if delay_after_elapsed_time_in_seconds >= 0:
                return delay_after_elapsed_time_in_seconds
            else:
                return random_delay_in_seconds

    def check_device_in(self):
        if self.device and self.device.checked_out_by == self.campaign.id:
            time.sleep(8)
            self.logger.info('Releasing device')
            self.device.check_in()

    def init_campaign(self):
        response = {
            'status': True,
            'errors': []
        }

        if self.campaign.status in (Campaign.STOPPING, Campaign.STOPPED):
            response['status'] = False
            response['errors'].append(f'Campaign status is {self.campaign.status}')

        if not self.campaign.posh_user:
            response['status'] = False
            response['errors'].append('Campaign has no posh user assigned')

        if not self.campaign.posh_user.is_active:
            response['status'] = False
            response['errors'].append(f'Posh User, {self.campaign.posh_user}, is disabled')

        if not self.campaign.posh_user.is_active_in_posh:
            response['status'] = False
            response['errors'].append(f'Posh user, {self.campaign.posh_user}, is inactive')

        return response

    def finalize_campaign(self, success, campaign_delay, duration):
        self.check_device_in()

        if not self.campaign.posh_user.is_active_in_posh:
            self.campaign.status = Campaign.STOPPING
            self.campaign.next_runtime = None
            self.campaign.queue_status = 'N/A'
            self.campaign.save(update_fields=['status'])
        elif self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED, Campaign.PAUSED, Campaign.STARTING):
            if not success and self.campaign.status not in (Campaign.STOPPED, Campaign.STOPPING):
                campaign_delay = 3600

            if not campaign_delay:
                campaign_delay = self.get_random_delay(duration)

            hours, remainder = divmod(campaign_delay, 3600)
            minutes, seconds = divmod(remainder, 60)

            self.campaign.status = Campaign.IDLE
            self.campaign.next_runtime = timezone.now() + datetime.timedelta(seconds=campaign_delay)
            self.campaign.save(update_fields=['status', 'next_runtime'])
            self.logger.info(f'Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds')

    def launch_app(self, client):
        app_launched = False
        retries = 0

        while not app_launched and retries < 2:
            app_launched = client.launch_app(self.campaign.posh_user.username)
            retries += 1

        if not app_launched and not self.campaign.posh_user.is_registered:
            self.campaign.posh_user.clone_installed = False
            self.campaign.posh_user.save(update_fields=['clone_installed'])

            return False

        return app_launched

    def reset_ip(self, reset_url):
        response = requests.get(reset_url)
        retries = 0

        while response.status_code != requests.codes.ok and retries < 3:
            self.logger.warning('IP reset failed, trying again')
            response = requests.get(reset_url)
            retries += 1
            time.sleep(1)

        if response.status_code == requests.codes.ok:
            self.logger.info(response.text)
            return True

        self.logger.info(f'Could not reset IP after {retries} retries. Sending campaign to the end of the line')

        self.campaign.status = Campaign.STARTING
        self.campaign.queue_status = 'Unknown'
        self.campaign.next_runtime = timezone.now()
        self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])

        return False

    def init_logger(self, logger_id=None):
        try:
            self.logger = LogGroup.objects.get(id=logger_id)
        except LogGroup.DoesNotExist:
            self.logger = LogGroup(campaign=self.campaign, posh_user=self.campaign.posh_user, created_date=timezone.now())
            self.logger.save()

    def install_clone(self, device):
        with AppClonerClient(device.serial, device.system_port, device.mjpeg_server_port, self.logger, self.campaign.posh_user.username) as client:
            if not self.campaign.posh_user.clone_installed:
                start_time = time.time()
                installed = client.add_clone()
                end_time = time.time()
                if installed:
                    time_to_install = datetime.timedelta(seconds=round(end_time - start_time))

                    self.logger.info(f'Time to install clone: {time_to_install}')

                    self.campaign.posh_user.clone_installed = installed
                    self.campaign.posh_user.device = device
                    self.campaign.posh_user.time_to_install_clone = time_to_install
                    self.campaign.posh_user.save(update_fields=['clone_installed', 'device', 'time_to_install_clone'])

                    device.refresh_from_db(fields=['installed_clones'])
                    device.installed_clones += 1
                    device.save(update_fields=['installed_clones'])

            if not self.campaign.posh_user.app_package:
                app_launched = self.launch_app(client)

                if not app_launched:
                    return False

                clone_app_package = client.driver.current_package

                while 'poshmark' not in clone_app_package:
                    self.logger.info(f'App did not launch properly. Current app package {clone_app_package}')
                    app_launched = self.launch_app(client)

                    if not app_launched:
                        return False

                    time.sleep(.5)
                    clone_app_package = client.driver.current_package

                self.campaign.posh_user.app_package = clone_app_package
                self.campaign.posh_user.save(update_fields=['app_package'])

        return self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package

    def register(self, list_items, device):
        ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            with MobilePoshMarkClient(device.serial, device.system_port, device.mjpeg_server_port, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                if client.driver.current_package != self.campaign.posh_user.app_package:
                    app_launched = self.launch_app(client)

                    if not app_launched:
                        return False

                start_time = time.time()
                registered = client.register()
                end_time = time.time()

                if registered:
                    time_to_register = datetime.timedelta(seconds=round(end_time - start_time))

                    self.campaign.posh_user.time_to_register = time_to_register
                    self.logger.info(f'Time to register user: {time_to_register}')

                self.campaign.posh_user.is_registered = registered
                self.campaign.posh_user.save(update_fields=['time_to_register', 'is_registered'])

                if registered:
                    finish_registration_and_list = self.finish_registration(device, list_items, False, client)

                client.driver.press_keycode(3)

            if not (registered and finish_registration_and_list) and self.campaign.status == Campaign.RUNNING:
                self.logger.info('Restarting campaign due to error')
                self.campaign.status = Campaign.STARTING
                self.campaign.queue_status = 'Unknown'
                self.campaign.next_runtime = timezone.now()
                self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])

                return False

            return True

        return False

    def finish_registration(self, device, list_items=True, reset_ip=True, client=None):
        ip_reset = not reset_ip
        listed = not list_items

        if reset_ip:
            ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            if client:
                start_time = time.time()
                registration_finished = client.finish_registration()
                end_time = time.time()

                if registration_finished:
                    time_to_finish_registration = datetime.timedelta(seconds=round(end_time - start_time))
                    self.campaign.posh_user.time_to_finish_registration = time_to_finish_registration
                    self.logger.info(f'Time to finish registration: {time_to_finish_registration} seconds')

                self.campaign.posh_user.finished_registration = registration_finished
                self.campaign.posh_user.save(update_fields=['time_to_finish_registration', 'finished_registration'])

                if registration_finished and list_items:
                    listed = self.list_items(device, False, client)

                client.driver.press_keycode(3)
            else:
                with MobilePoshMarkClient(device.serial, device.system_port, device.mjpeg_server_port, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                    if client.driver.current_package != self.campaign.posh_user.app_package:
                        app_launched = self.launch_app(client)

                        if not app_launched:
                            return False

                    start_time = time.time()
                    registration_finished = client.finish_registration()
                    end_time = time.time()

                    if registration_finished:
                        time_to_finish_registration = datetime.timedelta(seconds=round(end_time - start_time))

                        self.campaign.posh_user.time_to_finish_registration = time_to_finish_registration
                        self.logger.info(f'Time to finish registration: {time_to_finish_registration}')

                    self.campaign.posh_user.finished_registration = registration_finished
                    self.campaign.posh_user.save(update_fields=['time_to_finish_registration', 'finished_registration'])

                    if registration_finished and list_items:
                        listed = self.list_items(device, False, client)

                    client.driver.press_keycode(3)

            if not (registration_finished and listed) and self.campaign.status == Campaign.RUNNING:
                self.logger.info('Did not list properly or finish registration. Restarting campaign')
                self.campaign.status = Campaign.STARTING
                self.campaign.queue_status = 'Unknown'
                self.campaign.next_runtime = timezone.now()
                self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])
                return False

            return True

        return False

    def list_items(self, device, reset_ip=True, client=None):
        ip_reset = not reset_ip

        if reset_ip:
            ip_reset = self.reset_ip(device.ip_reset_url)

        if ip_reset:
            item_listed = False
            items_to_list = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED)

            if client:
                for item_to_list in items_to_list:
                    listing_images = ListingImage.objects.filter(listing=item_to_list.listing)

                    start_time = time.time()
                    item_listed = client.list_item(item_to_list.listing, listing_images)
                    end_time = time.time()
                    time_to_list = datetime.timedelta(seconds=round(end_time - start_time))

                    if item_listed:
                        self.logger.info(f'Time to list item: {time_to_list}')

                        listed_item_id = client.get_listed_item_id()

                        self.logger.info(f'Listed item ID: {listed_item_id}')

                        item_to_list.listed_item_id = listed_item_id
                        item_to_list.time_to_list = time_to_list
                        item_to_list.status = ListedItem.UNDER_REVIEW
                        item_to_list.datetime_listed = timezone.now()
                        item_to_list.save(update_fields=['time_to_list', 'status', 'datetime_listed', 'listed_item_id'])
            else:
                with MobilePoshMarkClient(device.serial, device.system_port, device.mjpeg_server_port, self.campaign, self.logger, self.campaign.posh_user.app_package) as client:
                    if client.driver.current_package != self.campaign.posh_user.app_package:
                        app_launched = self.launch_app(client)

                        if not app_launched:
                            return False

                    for item_to_list in items_to_list:
                        listing_images = ListingImage.objects.filter(listing=item_to_list.listing)

                        start_time = time.time()
                        listed = client.list_item(item_to_list.listing, listing_images)
                        end_time = time.time()
                        time_to_list = datetime.timedelta(seconds=round(end_time - start_time))

                        if listed:
                            self.logger.info(f'Time to list item: {time_to_list}')

                            listed_item_id = client.get_listed_item_id()

                            self.logger.info(f'Listed item ID: {listed_item_id}')

                            item_to_list.listed_item_id = listed_item_id
                            item_to_list.time_to_list = time_to_list
                            item_to_list.status = ListedItem.UNDER_REVIEW
                            item_to_list.datetime_listed = timezone.now()
                            item_to_list.save(update_fields=['time_to_list', 'status', 'datetime_listed', 'listed_item_id'])

                            if not item_listed:
                                item_listed = listed

                    client.driver.press_keycode(3)

            if not item_listed and self.campaign.status == Campaign.RUNNING:
                self.logger.info('Did not list successfully. Restarting campaign.')

                self.campaign.status = Campaign.STARTING
                self.campaign.queue_status = 'Unknown'
                self.campaign.next_runtime = timezone.now()
                self.campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])
            else:
                all_items = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.UP)

                if all_items.count() == 0:
                    self.campaign.status = Campaign.PAUSED
                    self.campaign.save(update_fields=['status'])

            return item_listed

    def share_and_more(self):
        login_retries = 0
        update_profile_retries = 0
        profile_updated = self.campaign.posh_user.profile_updated
        listing_shared = None
        shared = None
        with PoshMarkClient(self.campaign, self.logger) as client:
            client.web_driver.get('https://poshmark.com')
            client.load_cookies()
            logged_in = client.check_logged_in()

            while not logged_in and login_retries < 3:
                logged_in = client.login(login_retries)
                login_retries += 1

            if logged_in:
                while not profile_updated and update_profile_retries < 3 and logged_in:
                    profile_updated = client.update_profile(update_profile_retries)
                    update_profile_retries += 1

                    if profile_updated:
                        self.campaign.posh_user.profile_updated = True
                        self.campaign.posh_user.save(update_fields=['profile_updated'])

                # Follow random users and report a random listing
                random_number = random.random()
                if random_number < 0.1:
                    client.follow_random_follower()
                elif random_number < 0.4:
                    client.follow_random_user()
                elif random_number < .7:
                    # Get a list of reported item IDs by the given posh_user
                    reported_item_ids = ListedItemReport.objects.filter(posh_user=self.campaign.posh_user).values_list('listed_item_to_report__listed_item_id', flat=True)

                    # Get a random unreported item by the given posh_user
                    unreported_items = ListedItemToReport.objects.exclude(listed_item_id__in=reported_item_ids)

                    if unreported_items:
                        unreported_item = random.choice(unreported_items)

                        reported = client.report_listing(unreported_item.listed_item_id)

                        if reported:
                            ListedItemReport.objects.create(posh_user=self.campaign.posh_user, listed_item_to_report=unreported_item)
                            bundle_message = 'If you don’t stop flagging my accounts I will start flagging you back just as heavily.'
                            client.send_private_bundle_message(unreported_item.listed_item_id, bundle_message)

                            if random_number < .05:
                                comments = [
                                    "LOL, people still fall for this? Come on!",
                                    "Are you serious? This is like scamming 101.",
                                    "Hey folks, just a heads up: don't get played by this super obvious scam",
                                    "Scammers be like, 'Let's see how much we can shock them today!'",
                                    "This thing stinks worse than a fish market in July. Total scam.",
                                    "Do yourself a favor and don't touch this scam with a ten-foot pole.",
                                    "Anybody with half a brain can tell this is a straight up scam.",
                                    "cmon, don't be clueless classic scam in action right here",
                                    "Believing this? Might as well believe pigs can fly... Total nonsense.",
                                    "You'd need a lobotomy to think this isn't a scam. Seriously....",
                                    "LOL, this is such an obvious fake!",
                                    "OMG, who actually falls for this? It's a total scam!",
                                    "No way, Jose! This is like the definition of fake.",
                                    "Pssst... Don't even think about believing this crap. It's fake AF.",
                                    "Haha, nice try scammers! This is faker than fake.",
                                    "Hey everyone, check out the scam of the day right here!",
                                    "Ugh, these scams are getting dumber by the minute.",
                                    "Yeah right, like anyone's gonna buy into this nonsense.",
                                    "Just another day, just another ridiculous scam attempt.",
                                    "Sigh... Can't believe people still try to pull off these fakes.",
                                    'fake',
                                    'scam'
                                ]

                                client.comment_on_listing(unreported_item.listed_item_id, random.choice(comments))
                        elif reported is False:
                            unreported_items.delete()

                shareable_listed_items = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.UP).exclude(listed_item_id='')

                if shareable_listed_items:
                    for listed_item in shareable_listed_items:
                        listing_shared_retries = 0
                        while listing_shared is None and listing_shared_retries < 3:
                            listing_shared = client.share_item(listed_item.listed_item_id, listed_item.listing_title)
                            listing_shared_retries += 1

                        if not shared:
                            shared = listing_shared
                        listing_shared = None

                        if random.random() < .20 and shared:
                            self.logger.info('Seeing if it is time to send offers to likers')
                            now = timezone.now()
                            nine_pm = datetime.datetime(year=now.year, month=now.month, day=now.day, hour=2,
                                                        minute=0, second=0).replace(tzinfo=pytz.utc)
                            midnight = nine_pm + datetime.timedelta(hours=3)

                            if nine_pm < now < midnight:
                                client.send_offer_to_likers(listed_item)
                            else:
                                self.logger.info(f"Not the time to send offers to likers. Current Time: {now.astimezone(pytz.timezone('US/Eastern')).strftime('%I:%M %p')} Eastern")

                        if random.random() < .20 and shared:
                            client.check_offers(listed_item.listing_title)

                        if random.random() < .50 and shared:
                            client.check_comments(listed_item.listed_item_id, listed_item.listing_title)

                    return shared
                else:
                    all_listed_items = ListedItem.objects.filter(posh_user=self.campaign.posh_user)
                    reserved_listed_items = all_listed_items.filter(status=ListedItem.RESERVED)
                    under_review_listed_items = all_listed_items.filter(status=ListedItem.UNDER_REVIEW)
                    sold_listed_items = all_listed_items.filter(status=ListedItem.SOLD)
                    if reserved_listed_items:
                        self.logger.info('This user has no shareable listings but has some reserved. Setting delay to an hour.')

                        return False
                    elif under_review_listed_items:
                        self.logger.info('This user has no shareable listings but has some under review. Pausing campaign')

                        self.campaign.status = Campaign.PAUSED
                        self.campaign.next_runtime = None
                        self.campaign.save()

                        return False
                    elif sold_listed_items:
                        self.logger.info('This user has no shareable listings and only ones sold. Stopping campaign')

                        self.campaign.status = Campaign.STOPPING
                        self.campaign.next_runtime = None
                        self.campaign.save()

                        return False
                    else:
                        self.logger.info('This user has no listings for sale. Stopping campaign')

                        self.campaign.status = Campaign.STOPPING
                        self.campaign.next_runtime = None
                        self.campaign.save()

                        return False

            else:
                self.logger.info('Stopping campaign because user could not log in')

                self.campaign.status = Campaign.STOPPING
                self.campaign.save(update_fields=['status'])
                return False

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED):
            self.campaign.status = Campaign.STARTING
            self.campaign.next_runtime = timezone.now()
            self.campaign.queue_status = 'Unknown'
            self.campaign.save(update_fields=['status', 'next_runtime', 'queue_status'])

        if type(exc) is WebDriverException and self.device.checked_out_by == self.campaign.id:
            client = AdbClient(host=os.environ.get('LOCAL_SERVER_IP'), port=5037)
            adb_device = client.device(serial=self.device.serial)

            self.logger.warning('Rebooting device')
            adb_device.reboot()
        elif type(exc) in (SoftTimeLimitExceeded, TimeLimitExceeded):
            self.logger.warning('Campaign ended because it exceeded the run time allowed')

        self.finalize_campaign(False, None, 0)

        exc_type, exc_value, exc_traceback = einfo.exc_info
        self.logger.error(f'Campaign failed due to {exc_type}: {exc_value}')
        self.logger.debug(traceback.format_exc())

        self.logger.info('Campaign was sent to the end of the line and will start soon')

    def run(self, campaign_id, logger_id=None, device_id=None, attempt=1, *args, **kwargs):
        self.campaign = Campaign.objects.get(id=campaign_id)
        campaign_delay = None

        self.init_logger(logger_id)

        campaign_init = self.init_campaign()

        if campaign_init['status']:
            self.logger.info(f'Campaign, {self.campaign.title}, started for {self.campaign.posh_user.username}')

            try:
                self.device = Device.objects.get(id=device_id)
                self.device.checkout_time = timezone.now()
                self.device.save()
            except Device.DoesNotExist:
                pass

            self.campaign.status = Campaign.RUNNING
            self.campaign.queue_status = 'N/A'
            self.campaign.save(update_fields=['status', 'queue_status'])

            items_to_list = ListedItem.objects.filter(posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED)
            need_to_list = items_to_list.count() > 0

            start_time = time.time()

            if not (self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package) and self.device and self.campaign.mode == Campaign.ADVANCED_SHARING:
                installed = self.install_clone(self.device)
            elif self.campaign.posh_user.clone_installed and self.campaign.posh_user.app_package and self.device and self.campaign.mode == Campaign.ADVANCED_SHARING:
                installed = True
            else:
                installed = False

            if installed and not self.campaign.posh_user.is_registered:
                success = self.register(device=self.device, list_items=need_to_list)
            elif installed and not self.campaign.posh_user.finished_registration:
                success = self.finish_registration(device=self.device, list_items=need_to_list, reset_ip=True)
            elif installed and items_to_list:
                success = self.list_items(self.device)
            elif self.campaign.posh_user.is_registered and self.campaign.mode in (Campaign.ADVANCED_SHARING, Campaign.BASIC_SHARING):
                success = self.share_and_more()
            else:
                self.campaign.status = Campaign.STOPPING
                self.campaign.save(update_fields=['status'])

                success = False

            end_time = time.time()
            duration = end_time - start_time

            self.finalize_campaign(success, campaign_delay, duration)
        else:
            self.logger.info(f'Campaign could not be initiated due to the following issues {", ".join(campaign_init["errors"])}')
        self.logger.info('Campaign ended')


class ManageCampaignsTask(Task):
    def __init__(self):
        self.soft_time_limit = 240
        self.time_limit = 450
        self.logger = logging.getLogger(__name__)

    def get_available_device(self, needed_device=None):
        devices = Device.objects.filter(is_active=True)
        if needed_device:
            devices = devices.filter(id=needed_device.id)
        else:
            devices = devices.filter(installed_clones__lt=147)
        in_use_ip_reset_urls = Device.objects.filter(checked_out_by__isnull=False).values_list('ip_reset_url', flat=True)

        for device in devices:
            if device.ip_reset_url not in in_use_ip_reset_urls and not device.checked_out_by:
                if device.is_ready():
                    return device

            runtime = (timezone.now() - device.checkout_time).total_seconds() if device.checkout_time is not None else None
            if runtime and device.checked_out_by and runtime > CampaignTask.time_limit:
                try:
                    campaign = Campaign.objects.get(id=device.checked_out_by)
                    if campaign.status != Campaign.RUNNING:
                        self.logger.warning('Campaign isn\'t running, checking in.')
                        device.check_in()
                    elif runtime > CampaignTask.time_limit * 2:
                        self.logger.warning(f'Campaign has been running for {runtime} sec, checking in.')
                        device.check_in()
                        campaign.status = Campaign.STARTING
                        campaign.save()
                except Campaign.DoesNotExist:
                    self.logger.warning('Campaign does not exist. Checking in.')
                    device.check_in()

    def start_campaign(self, campaign, device=None):
        if device:
            try:
                device.check_out(campaign.id)

                campaign.status = Campaign.IN_QUEUE
                campaign.queue_status = 'N/A'

                campaign.save(update_fields=['status', 'queue_status'])

                CampaignTask.delay(campaign.id, device_id=device.id)
                self.logger.info(f'Campaign Started: {campaign.title} for {campaign.posh_user.username} on {device.serial}')

                return True
            except ValueError:
                self.logger.info(f'Device: {device.serial} is not ready')
                if campaign.status == Campaign.IDLE:
                    campaign.status = Campaign.IN_QUEUE
                    campaign.queue_status = 'N/A'
                    campaign.save(update_fields=['status', 'queue_status'])

                    CampaignTask.delay(campaign.id)
                    self.logger.info(f'Campaign Started: {campaign.title} for {campaign.posh_user.username} with no device')

                    return True
        else:
            campaign.status = Campaign.IN_QUEUE
            campaign.queue_status = 'N/A'
            campaign.save(update_fields=['status', 'queue_status'])

            CampaignTask.delay(campaign.id)
            self.logger.info(f'Campaign Started: {campaign.title} for {campaign.posh_user.username} with no device')

            return True

    def run(self, *args, **kwargs):
        now = timezone.now()
        campaigns = Campaign.objects.filter(Q(status__in=[Campaign.STOPPING, Campaign.IDLE, Campaign.STARTING]) & (Q(next_runtime__lte=now) | Q(next_runtime__isnull=True))).order_by('next_runtime')
        queue_num = 1
        check_for_device = True

        for campaign in campaigns:
            campaign_started = False
            available_device = None
            items_to_list = ListedItem.objects.filter(posh_user=campaign.posh_user, status=ListedItem.NOT_LISTED)
            need_to_list = items_to_list.count() > 0

            if campaign.posh_user and check_for_device and (need_to_list or not campaign.posh_user.is_registered):
                available_device = self.get_available_device(campaign.posh_user.device)

            if campaign.status == Campaign.STOPPING or not campaign.posh_user or not campaign.posh_user.is_active or not campaign.posh_user.is_active_in_posh:
                campaign.status = Campaign.STOPPED
                campaign.queue_status = 'N/A'
                campaign.next_runtime = None

                campaign.save(update_fields=['status', 'queue_status', 'next_runtime'])
            elif campaign.status == Campaign.IDLE and campaign.next_runtime is not None:
                campaign_started = self.start_campaign(campaign, available_device)
            elif campaign.status == Campaign.STARTING and (available_device or (not need_to_list and campaign.posh_user.is_registered)):
                campaign_started = self.start_campaign(campaign, available_device)

            if (not campaign_started and campaign.status == Campaign.STARTING) or (not available_device and campaign.status == Campaign.STARTING):
                campaign.queue_status = str(queue_num)
                campaign.save(update_fields=['queue_status'])
                queue_num += 1

                if check_for_device and not campaign.posh_user.device:
                    check_for_device = False


CampaignTask = app.register_task(CampaignTask())
ManageCampaignsTask = app.register_task(ManageCampaignsTask())


@shared_task
def check_posh_users():
    logger = logging.getLogger(__name__)
    # logger.info('Checking posh users')
    posh_users = PoshUser.objects.filter(is_active_in_posh=True, is_registered=True)
    with PublicPoshMarkClient(logger) as client:
        for posh_user in posh_users:
            try:
                campaign = Campaign.objects.get(posh_user=posh_user)
            except Campaign.DoesNotExist:
                campaign = None

            all_posh_listed_items = client.get_all_listings(posh_user.username)
            if any(values for values in all_posh_listed_items.values() if values):
                for listed_item_type, posh_listed_items in all_posh_listed_items.items():
                    for posh_listed_item in posh_listed_items:
                        try:
                            listed_item_obj = ListedItem.objects.get(posh_user=posh_user, listed_item_id=posh_listed_item['id'])

                            if listed_item_type == 'shareable_listings' and listed_item_obj.status != ListedItem.UP:
                                if listed_item_obj.status == ListedItem.UNDER_REVIEW:
                                    listed_item_obj.datetime_passed_review = timezone.now()
                                    listed_item_obj.status = ListedItem.UP
                                    listed_item_obj.save(update_fields=['status', 'datetime_passed_review'])
                                elif listed_item_obj.status != ListedItem.UNDER_REVIEW:
                                    listed_item_obj.status = ListedItem.UP
                                    listed_item_obj.save(update_fields=['status'])

                            elif listed_item_type == 'sold_listings' and listed_item_obj.status != ListedItem.SOLD:
                                listed_item_obj.datetime_sold = timezone.now()
                                listed_item_obj.status = ListedItem.SOLD

                                listed_item_obj.save(update_fields=['status', 'datetime_sold'])
                            elif listed_item_type == 'reserved_listings' and listed_item_obj.status != ListedItem.RESERVED:
                                listed_item_obj.status = ListedItem.RESERVED
                                listed_item_obj.save(update_fields=['status'])
                            elif listed_item_type == 'not_for_sale_listings':
                                listed_item_obj.status = ListedItem.NOT_FOR_SALE
                                listed_item_obj.save()

                        except ListedItem.DoesNotExist:
                            # logger.warning(f'Could not find a listed item for {posh_user} with title {posh_listed_item["title"]}.')

                            if not campaign or campaign.status not in (Campaign.IDLE, Campaign.RUNNING, Campaign.STARTING):
                                # logger.warning(f'Creating the listed item now...')

                                try:
                                    listing = Listing.objects.get(title=posh_listed_item['title'])
                                except Listing.DoesNotExist:
                                    listing = None

                                listed_item_obj = ListedItem(posh_user=posh_user, listing=listing, listing_title=posh_listed_item['title'], listed_item_id=posh_listed_item['id'])

                                if listed_item_type == 'reserved_listings':
                                    listed_item_obj.status = ListedItem.RESERVED
                                elif listed_item_type == 'sold_listings':
                                    listed_item_obj.datetime_sold = timezone.now()
                                    listed_item_obj.status = ListedItem.SOLD
                                elif listed_item_type == 'not_for_sale_listings':
                                    listed_item_obj.status = ListedItem.NOT_FOR_SALE
                                else:
                                    listed_item_obj.status = ListedItem.UP

                                listed_item_obj.save()
                        except ListedItem.MultipleObjectsReturned:
                            pass

                if (all_posh_listed_items['shareable_listings'] or all_posh_listed_items['reserved_listings']) and campaign and campaign.status == Campaign.PAUSED:
                    # logger.info('User has shareable listings and its campaign is paused. Resuming...')
                    campaign.next_runtime = timezone.now()
                    campaign.queue_status = 'CALCULATING'
                    campaign.status = Campaign.STARTING
                    campaign.save(update_fields=['next_runtime', 'queue_status', 'status'])

                all_posh_listed_item_ids = [value['id'] for sublist in all_posh_listed_items.values() for value in sublist]
                for listed_item in ListedItem.objects.filter(posh_user=posh_user, status=ListedItem.UP):
                    if listed_item.listed_item_id not in all_posh_listed_item_ids:
                        # logger.info(f'{listed_item.listing_title} is not in the listed items. Changing to removed.')
                        listed_item.status = ListedItem.REMOVED
                        listed_item.datetime_removed = timezone.now()
                        listed_item.save(update_fields=['status', 'datetime_removed'])

                if ListedItem.objects.filter(posh_user=posh_user, status__in=(ListedItem.UP, ListedItem.RESERVED, ListedItem.UNDER_REVIEW, ListedItem.NOT_LISTED)).count() == 0 and campaign and campaign.status not in (Campaign.STOPPING, Campaign.STOPPED):
                    campaign.status = Campaign.STOPPING
                    campaign.save(update_fields=['status'])

            # Checks if the user is inactive when there are no listings
            if sum([len(y) for y in all_posh_listed_items.values()]) == 0:
                # logger.info('User has no listings available...')
                is_active_in_posh = client.check_inactive(posh_user.username)

                if not is_active_in_posh:
                    posh_user.is_active_in_posh = False
                    posh_user.save(update_fields=['is_active_in_posh'])

                    if campaign:
                        # logger.info('Stopping campaign...')
                        campaign.status = Campaign.STOPPING
                        campaign.save(update_fields=['status'])


@shared_task
def log_cleanup():
    campaigns = Campaign.objects.all()

    for campaign in campaigns:
        logs = LogGroup.objects.filter(campaign=campaign).order_by('-created_date')[5:]

        for log in logs:
            log.delete()


@shared_task
def posh_user_cleanup():
    logger = logging.getLogger(__name__)
    day_ago = (timezone.now() - datetime.timedelta(days=1)).date()
    two_weeks_ago = (timezone.now() - datetime.timedelta(days=14)).date()

    # Get all posh_users who have been inactive for at least a day
    posh_users = PoshUser.objects.filter(is_active=False, date_disabled__lt=day_ago)

    for posh_user in posh_users:
        if posh_user.app_package and posh_user.device and posh_user.clone_installed:
            client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
            device = client.device(posh_user.device.serial)

            if device:
                device.uninstall(posh_user.app_package)

                if posh_user.device.installed_clones > 0:
                    posh_user.device.installed_clones -= 1
                    posh_user.device.save(update_fields=['installed_clones'])

            posh_user.clone_installed = False
            posh_user.device = None
            posh_user.save(update_fields=['clone_installed', 'device'])

        if posh_user.date_disabled < two_weeks_ago:
            posh_user.delete()


@shared_task
def send_support_emails():
    logger = logging.getLogger(__name__)
    smtp_server = 'smtp.mail.yahoo.com'
    smtp_port = 587
    posh_users = PoshUser.objects.filter(is_active=True, send_support_email=True)
    all_email_info = PaymentEmailContent.objects.all()
    recipients = ['support@yahoo.com', 'hello@poshmark.com']

    if all_email_info:
        for posh_user in posh_users:
            if posh_user.email and posh_user.email_imap_password:
                email_info: PaymentEmailContent = random.choice(all_email_info)
                body = email_info.body
                body = body.replace('{{user_name}}', posh_user.username)
                body = body.replace('{{email}}', posh_user.email)

                # Check if last support email was sent at least 24 hours ago
                if (not posh_user.date_last_support_email or (timezone.now() - posh_user.date_last_support_email) >= datetime.timedelta(hours=24)):
                    # Randomly decide whether to send an email (25% chance)
                    if random.random() <= 0.16:
                        msg = MIMEMultipart()
                        msg['From'] = posh_user.email
                        msg['To'] = ', '.join(recipients)
                        msg['Subject'] = email_info.subject
                        msg.attach(MIMEText(body, 'plain'))

                        try:
                            # Connect to the SMTP server
                            with smtplib.SMTP(smtp_server, smtp_port) as server:
                                server.starttls()
                                server.login(posh_user.email, posh_user.email_imap_password)

                                # Send the email
                                server.sendmail(posh_user.email, recipients, msg.as_string())
                                logger.info("Email sent successfully!")

                                # Update the date_last_support_email field
                                posh_user.date_last_support_email = timezone.now()
                                posh_user.save()

                        except Exception as e:
                            logger.error("An error occurred", exc_info=True)


@shared_task
def get_items_to_report():
    logger = LogGroup(campaign=Campaign.objects.filter(user__username='admin').first(), posh_user=Campaign.objects.filter(user__username='admin').first().posh_user, created_date=timezone.now())
    logger.save()

    with PublicPoshMarkClient(logger) as client:
        bad_listings = client.find_bad_listings()

        for listing in bad_listings:
            logger.info(listing[0])
            logger.info(f'https://poshmark.com/listing/{listing[1]}')


@shared_task
def check_sold_items():
    logger = logging.getLogger(__name__)
    sold_items = ListedItem.objects.filter(status=ListedItem.SOLD)

    sender_email = "orders@poshmark.com"

    for item in sold_items:
        listing_title = item.listing_title
        posh_user = item.posh_user
        sold_time = item.datetime_sold  # Assuming datetime_sold is the field storing the sold time

        # Check if the PoshUser has the necessary IMAP email password
        if posh_user.email and posh_user.email_imap_password:
            email_address = posh_user.email
            password = posh_user.email_imap_password

            # Construct the subject keyword with dynamic values
            subject_keyword = f'Your earnings from "{listing_title}"'

            matching_email = zke_yahoo.check_for_email(sender_email, email_address, password, subject_keyword, sold_time)

            if matching_email:
                date_format = '%m/%d/%Y %I:%M %p %Z'
                date_sold = item.datetime_sold.astimezone(pytz.timezone('US/Eastern')).strftime(date_format)

                date_received_str = matching_email.get("Date")
                date_received = datetime.datetime.strptime(date_received_str, '%a, %d %b %Y %H:%M:%S %z (%Z)').astimezone(pytz.timezone('US/Eastern')).strftime(date_format)

                log_message = (
                    f"New listed item is redeemable:\n"
                    f"Item: {item.listing_title}\n"
                    f"Date of Email: {date_received}\n"
                    f"Posh Username: {item.posh_user.username}\n"
                    f"Posh Password: {item.posh_user.password}\n"
                    f"Email: {item.posh_user.email}\n"
                    f"Email IMAP Password: {item.posh_user.email_imap_password}\n"
                )
                logger.info(log_message)
