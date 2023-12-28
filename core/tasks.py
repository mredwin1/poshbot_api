import asyncio
import datetime
import json
import logging
import os
import pytz
import random
import requests
import smtplib
import ssl
import time
import traceback

from bs4 import BeautifulSoup
from celery import shared_task, Task
from celery.beat import Scheduler
from celery.exceptions import TimeLimitExceeded, SoftTimeLimitExceeded
from decimal import Decimal
from django.core.cache import caches
from django.db.models import Q
from django.utils import timezone
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Union

from chrome_clients.clients import PoshmarkClient, OctoAPIClient
from chrome_clients.errors import (
    LoginOrRegistrationError,
    UserDisabledError,
    ShareError,
    ListingNotFoundError,
    NoLikesError,
    ProfileStartError,
)
from email_retrieval import zke_yahoo
from poshbot_api.celery import app
from .models import (
    Campaign,
    Listing,
    PoshUser,
    ListedItem,
    PaymentEmailContent,
    Proxy,
    BadPhrase,
)


class CustomBeatScheduler(Scheduler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def is_due(self, entry):
        # First, check if the task is due based on the default scheduler logic
        is_due, next_time_to_run = super().is_due(entry)

        if not is_due:
            # If the task is not due based on schedule, no further checks are needed
            return False, next_time_to_run

        # Proceed with the Redis check if the task is due
        key = entry.task
        cache = caches["default"]
        redis_client = cache.client.get_client()

        if redis_client.exists(key):
            # Task is already in progress, return False
            return False, next_time_to_run
        else:
            # Task is not in progress, start it and add the key
            redis_client.set(key, "scheduled", ex=1200)  # Set key with expiry
            return True, next_time_to_run


class CampaignTask(Task):
    def __init__(self):
        self.soft_time_limit = 300
        self.time_limit = 600
        self.campaign = None
        self.logger = None
        self.proxy = None
        self.proxy_id = None
        self.runtime_details = {}

    def get_runtime_details(self):
        octo_client = OctoAPIClient()
        proxy_uuid = ""
        proxy = None

        if self.proxy is not None:
            current_proxy = {
                "title": f"{self.proxy.vendor} {self.proxy.license_id}",
                "type": self.proxy.type,
                "port": self.proxy.port,
                "host": self.proxy.hostname,
                "login": self.proxy.username,
                "password": self.proxy.password,
                "external_id": self.proxy.license_id,
                "change_ip_url": f"https://portal.mobilehop.com/proxies/{self.proxy.proxy_uuid}/reset",
            }
            proxies = octo_client.get_proxies(external_id=self.proxy.license_id)

            if proxies:
                proxy = proxies[0]

                proxy_differences = {}
                for key, value in current_proxy.items():
                    if value != proxy[key]:
                        proxy_differences[key] = value

                if proxy_differences:
                    proxy = octo_client.update_proxy(proxy["uuid"], proxy_differences)
            else:
                proxy = octo_client.create_proxy(current_proxy)

            proxy_uuid = proxy["uuid"]

        if not self.campaign.posh_user.octo_uuid:
            tags = [
                os.environ["ENVIRONMENT"].replace("-", ""),
                self.campaign.user.username,
            ]
            if proxy:
                profile_uuid = octo_client.create_profile(
                    self.campaign.posh_user.username, tags, proxy_uuid=proxy_uuid
                )
            else:
                profile_uuid = octo_client.create_profile(
                    self.campaign.posh_user.username, tags
                )
            profile = octo_client.get_profile(profile_uuid)

            self.campaign.posh_user.octo_uuid = profile["uuid"]
            self.campaign.posh_user.save(update_fields=["octo_uuid"])

        else:
            profile = octo_client.get_profile(self.campaign.posh_user.octo_uuid)

        if proxy:
            octo_client.update_profile(profile["uuid"], proxy_uuid=proxy_uuid)
            profile["proxy"] = proxy
        elif not proxy and profile["proxy"]:
            octo_client.update_profile(profile["uuid"])

        width, height = map(
            int, profile["fingerprint"]["screen"].split(" ")[0].split("x")
        )

        try:
            start_response = octo_client.start_profile(profile["uuid"])
        except ProfileStartError as e:
            if "Profile is already started" in str(e):
                self.logger.warning(
                    f"Profile {profile['uuid']} already running force stopping..."
                )
                octo_client.force_stop_profile(profile["uuid"])
                time.sleep(5)
                start_response = octo_client.start_profile(profile["uuid"])
                self.logger.debug(f"Start response: {start_response}")
            else:
                start_response = {}

        runtime_details = start_response
        runtime_details["width"] = width
        runtime_details["height"] = height

        return runtime_details

    def stop_octo_profile(self):
        octo_client = OctoAPIClient()
        try:
            octo_client.stop_profile(self.runtime_details["uuid"])
        except KeyError:
            pass

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

    def check_proxy_in(self):
        if self.proxy and self.proxy.checked_out_by == self.campaign.id:
            self.logger.info("Releasing proxy")
            self.proxy.check_in()

    def init_campaign(self):
        response = {"status": True, "errors": []}

        if self.campaign.status in (Campaign.STOPPING, Campaign.STOPPED):
            response["status"] = False
            response["errors"].append(f"Campaign status is {self.campaign.status}")

        if not self.campaign.posh_user:
            response["status"] = False
            response["errors"].append("Campaign has no posh user assigned")

        if not self.campaign.posh_user.is_active:
            response["status"] = False
            response["errors"].append(
                f"Posh User, {self.campaign.posh_user}, is disabled"
            )

        if not self.campaign.posh_user.is_active_in_posh:
            response["status"] = False
            response["errors"].append(
                f"Posh user, {self.campaign.posh_user}, is inactive"
            )

        if not self.campaign.posh_user.is_registered and not self.proxy_id:
            response["status"] = False
            response["errors"].append(
                "Posh user is not registered but no proxy was given."
            )

        needs_to_list = ListedItem.objects.filter(
            posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED
        ).exists()
        if needs_to_list and not self.proxy_id:
            response["status"] = False
            response["errors"].append("Posh user needs to list but no proxy was given.")

        if self.proxy_id:
            self.proxy = Proxy.objects.get(id=self.proxy_id)

            self.proxy.checkout_time = timezone.now()
            self.proxy.save(update_fields=["checkout_time"])

            ip_reset = self.reset_ip()

            if not ip_reset:
                response["status"] = False
                response["errors"].append("IP reset unsuccessful")

        return response

    def finalize_campaign(self, success, campaign_delay, duration):
        self.stop_octo_profile()
        self.check_proxy_in()

        if self.campaign.status not in (
            Campaign.STOPPING,
            Campaign.STOPPED,
            Campaign.PAUSED,
            Campaign.STARTING,
        ):
            if not success and self.campaign.status not in (
                Campaign.STOPPED,
                Campaign.STOPPING,
            ):
                campaign_delay = 3600

            if not campaign_delay:
                campaign_delay = self.get_random_delay(duration)

            hours, remainder = divmod(campaign_delay, 3600)
            minutes, seconds = divmod(remainder, 60)

            self.campaign.status = Campaign.IDLE
            self.campaign.next_runtime = timezone.now() + datetime.timedelta(
                seconds=campaign_delay
            )
            self.campaign.save(update_fields=["status", "next_runtime"])
            self.logger.info(
                f"Campaign will start back up in {round(hours)} hours {round(minutes)} minutes and {round(seconds)} seconds"
            )

    def reset_ip(self):
        reset_success = self.proxy.reset_ip()

        if reset_success:
            self.logger.info(reset_success)
            time.sleep(10)
            return True

        self.logger.info(f"Could not reset IP. Sending campaign to the end of the line")

        self.campaign.status = Campaign.STARTING
        self.campaign.queue_status = "Unknown"
        self.campaign.next_runtime = timezone.now() + datetime.timedelta(seconds=60)
        self.campaign.save(update_fields=["status", "queue_status", "next_runtime"])

        return False

    def init_logger(self, logger_id=None):
        logger = logging.getLogger(__name__)

        return logger

    async def register(self, list_items):
        ws_endpoint = self.runtime_details["ws_endpoint"]
        width = self.runtime_details["width"]
        height = self.runtime_details["height"]
        async with PoshmarkClient(ws_endpoint, width, height, self.logger) as client:
            start_time = time.perf_counter()
            user_info = self.campaign.posh_user.user_info
            user_info["profile_picture"] = self.campaign.posh_user.get_profile_picture()

            try:
                username = await client.register(user_info)

                update_fields = ["is_registered"]
                if username != user_info["username"]:
                    self.campaign.posh_user.username = username
                    update_fields.append("username")

                self.campaign.posh_user.is_registered = True
                await self.campaign.posh_user.asave()
                await client.finish_registration(user_info)
                os.remove(user_info["profile_picture"])
                end_time = time.perf_counter()

                time_to_register = datetime.timedelta(
                    seconds=round(end_time - start_time)
                )
                self.logger.info(f"Time to register user: {time_to_register}")
                self.campaign.posh_user.time_to_register = time_to_register
                await self.campaign.posh_user.asave(update_fields=["time_to_register"])

                if list_items:
                    success = await self.list_items(client)
                    campaign_status = Campaign.PAUSED
                else:
                    success = True
                    campaign_status = Campaign.IDLE

            except LoginOrRegistrationError as e:
                success = False
                self.logger.error(e)
                error_str = str(e)
                if "form__error" in error_str:
                    self.logger.warning("Stopping campaign and setting user inactive")
                    self.campaign.posh_user.is_active = False
                    await self.campaign.posh_user.asave(update_fields=["is_active"])

                campaign_status = Campaign.STOPPING
            except Exception as e:
                success = False
                self.logger.exception(e, exc_info=True)
                self.logger.info("Restarting campaign due to error")
                campaign_status = Campaign.STARTING

        self.campaign.status = campaign_status
        self.campaign.queue_status = "Unknown"
        self.campaign.next_runtime = timezone.now()
        await self.campaign.asave(
            update_fields=["status", "queue_status", "next_runtime"]
        )

        return success

    async def _list_items(self, client):
        self.logger.info("delete_me: listing item")
        items_to_list = ListedItem.objects.filter(
            posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED
        ).select_related("listing")
        async for item_to_list in items_to_list:
            self.logger.info(f"delete_me: listing item  - {item_to_list}")
            user_info = self.campaign.posh_user.user_info
            item_info = item_to_list.item_info
            item_info["photos"] = await item_to_list.get_images()
            start_time = time.time()
            try:
                listed_item = await client.list_item(user_info, item_info)
                end_time = time.time()
                time_to_list = datetime.timedelta(seconds=round(end_time - start_time))

                self.logger.info(f"Time to list item: {time_to_list}")
                self.logger.info(f"Listed item ID: {listed_item['listing_id']}")

                item_to_list.listed_item_id = listed_item["listing_id"]
                item_to_list.time_to_list = time_to_list
                item_to_list.status = ListedItem.UNDER_REVIEW
                item_to_list.datetime_listed = timezone.now()
                await item_to_list.asave(
                    update_fields=[
                        "time_to_list",
                        "status",
                        "datetime_listed",
                        "listed_item_id",
                    ]
                )

            except UserDisabledError as e:
                self.logger.error(e)
                self.logger.warning("Stopping campaign.")

                self.campaign.status = Campaign.STOPPING
                self.campaign.queue_status = "N/A"
                self.campaign.next_runtime = None
                await self.campaign.asave(
                    update_fields=["status", "queue_status", "next_runtime"]
                )

                return False

        return True

    async def list_items(self, client=None):
        if client:
            item_listed = await self._list_items(client)
        else:
            ws_endpoint = self.runtime_details["ws_endpoint"]
            width = self.runtime_details["width"]
            height = self.runtime_details["height"]
            async with PoshmarkClient(
                ws_endpoint, width, height, self.logger
            ) as client:
                item_listed = await self._list_items(client)

        if not item_listed and self.campaign.status == Campaign.RUNNING:
            self.logger.info("Did not list successfully. Restarting campaign.")

            self.campaign.status = Campaign.STARTING
            self.campaign.queue_status = "Unknown"
            self.campaign.next_runtime = timezone.now() + datetime.timedelta(seconds=60)
            await self.campaign.asave(
                update_fields=["status", "queue_status", "next_runtime"]
            )
        else:
            all_items = ListedItem.objects.filter(
                posh_user=self.campaign.posh_user, status=ListedItem.UP
            )

            if await all_items.acount() == 0:
                self.campaign.status = Campaign.PAUSED
                await self.campaign.asave(update_fields=["status"])

        return item_listed

    async def share_and_more(self):
        # profile_updated = self.campaign.posh_user.profile_updated
        ws_endpoint = self.runtime_details["ws_endpoint"]
        width = self.runtime_details["width"]
        height = self.runtime_details["height"]
        listing_shared = None
        user_info = self.campaign.posh_user.user_info
        async with PoshmarkClient(ws_endpoint, width, height, self.logger) as client:
            # TODO: Implement the below
            # if not profile_updated:
            #     await client.update_profile(update_profile_retries)
            #
            #     self.campaign.posh_user.profile_updated = True
            #     self.campaign.posh_user.save(update_fields=["profile_updated"])

            # TODO: Implement the below
            # Follow random users and report a random listing
            # random_number = random.random()
            # if random_number < 0.1:
            #     client.follow_random_follower()
            # elif random_number < 0.4:
            #     client.follow_random_user()

            # TODO: Implement the below
            # Get a list of listed item IDs the user has listed
            # user_listed_item_ids = ListedItem.objects.filter(
            #     posh_user=self.campaign.posh_user
            # ).values_list("listed_item_id", flat=True)
            #
            # # Get a list of reported item IDs by the given posh_user
            # reported_item_ids = ListedItemReport.objects.filter(
            #     posh_user=self.campaign.posh_user
            # ).values_list("listed_item_to_report__listed_item_id", flat=True)
            #
            # excluded_items = user_listed_item_ids.union(reported_item_ids)
            #
            # # Get a random unreported item by the given posh_user
            # unreported_items = ListedItemToReport.objects.exclude(
            #     listed_item_id__in=excluded_items
            # )
            #
            # if unreported_items:
            #     unreported_item = random.choice(unreported_items)
            #
            #     reported = client.report_listing(
            #         unreported_item.listed_item_id, unreported_item.report_type
            #     )
            #
            #     if reported:
            #         ListedItemReport.objects.create(
            #             posh_user=self.campaign.posh_user,
            #             listed_item_to_report=unreported_item,
            #         )
            #     elif reported is False:
            #         # unreported_items.delete()
            #         pass
            #

            shareable_listings = ListedItem.objects.filter(
                posh_user=self.campaign.posh_user, status=ListedItem.UP
            ).exclude(listed_item_id="")

            if await shareable_listings.aexists():
                async for shareable_listing in shareable_listings:
                    try:
                        await client.share_listing(
                            user_info, shareable_listing.listed_item_id
                        )
                    except (ShareError, ListingNotFoundError) as e:
                        self.logger.warning(e)

                    if random.random() < 0.20:
                        self.logger.info(
                            "Seeing if it is time to send offers to likers"
                        )
                        now = timezone.now()
                        nine_pm = datetime.datetime(
                            year=now.year,
                            month=now.month,
                            day=now.day,
                            hour=2,
                            minute=0,
                            second=0,
                        ).replace(tzinfo=pytz.utc)
                        midnight = nine_pm + datetime.timedelta(hours=3)

                        if nine_pm < now < midnight:
                            try:
                                offer = shareable_listing.listing.listing_price * 0.9
                                await client.send_offers_to_likers(
                                    user_info, shareable_listing.listed_item_id, offer
                                )
                            except NoLikesError as e:
                                self.logger.warning(e)
                        else:
                            self.logger.info(
                                f"Not the time to send offers to likers. Current Time: {now.astimezone(pytz.timezone('US/Eastern')).strftime('%I:%M %p')} Eastern"
                            )
                    # TODO: Finish implementing this
                    # if random.random() < 0.20:
                    #     await client.check_offers(
                    #         user_info, shareable_listing.listed_item_id
                    #     )

                    bad_phrases = BadPhrase.objects.all()
                    bad_phrases = [
                        {"word": phrase.phrase, "report_type": phrase.report_type}
                        async for phrase in bad_phrases
                    ]
                    await client.check_comments(
                        user_info, shareable_listing.listed_item_id, bad_phrases
                    )

                return True
            else:
                all_listed_items = ListedItem.objects.filter(
                    posh_user=self.campaign.posh_user
                )
                reserved_listed_items = await all_listed_items.filter(
                    status=ListedItem.RESERVED
                ).aexists()
                under_review_listed_items = await all_listed_items.filter(
                    status=ListedItem.UNDER_REVIEW
                ).aexists()
                if reserved_listed_items:
                    self.logger.info(
                        "This user has no shareable listings but has some reserved. Setting delay to an hour."
                    )

                    return False
                elif under_review_listed_items:
                    self.logger.info(
                        "This user has no shareable listings but has some under review. Pausing campaign"
                    )

                    self.campaign.status = Campaign.PAUSED
                    self.campaign.next_runtime = None
                    await self.campaign.asave()

                    return False

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        exc_type, exc_value, exc_traceback = einfo.exc_info
        self.logger.error(f"Campaign failed due to {exc_type}: {exc_value}")
        self.logger.debug(traceback.format_exc())

        if type(exc) in (SoftTimeLimitExceeded, TimeLimitExceeded):
            self.logger.warning(
                "Campaign ended because it exceeded the run time allowed"
            )

        if self.campaign.status not in (Campaign.STOPPING, Campaign.STOPPED):
            self.logger.info(
                "Campaign was sent to the end of the line and will start soon"
            )
            self.campaign.status = Campaign.STARTING
            self.campaign.next_runtime = timezone.now() + datetime.timedelta(seconds=60)
            self.campaign.queue_status = "Unknown"
            self.campaign.save(update_fields=["status", "next_runtime", "queue_status"])

        self.finalize_campaign(False, None, 0)

    def run(
        self,
        campaign_id,
        logger_id=None,
        proxy_id=None,
        *args,
        **kwargs,
    ):
        self.campaign = (
            Campaign.objects.filter(id=campaign_id).select_related("posh_user").first()
        )
        self.logger = self.init_logger(logger_id)
        self.proxy = None
        self.proxy_id = proxy_id
        campaign_delay = None
        campaign_init = self.init_campaign()

        if campaign_init["status"]:
            self.logger.info(
                f"Campaign, {self.campaign.title}, started for {self.campaign.posh_user.username}"
            )

            self.runtime_details = self.get_runtime_details()

            self.campaign.status = Campaign.RUNNING
            self.campaign.queue_status = "N/A"
            self.campaign.save(update_fields=["status", "queue_status"])

            need_to_list = ListedItem.objects.filter(
                posh_user=self.campaign.posh_user, status=ListedItem.NOT_LISTED
            ).exists()

            start_time = time.time()

            if self.proxy and not self.campaign.posh_user.is_registered:
                success = asyncio.run(self.register(list_items=need_to_list))
            elif self.proxy and need_to_list:
                success = asyncio.run(self.list_items())
            elif self.campaign.posh_user.is_registered and self.campaign.mode in (
                Campaign.ADVANCED_SHARING,
                Campaign.BASIC_SHARING,
            ):
                success = asyncio.run(self.share_and_more())
            else:
                self.logger.info("Seems there is nothing to do")
                success = False

            end_time = time.time()
            duration = end_time - start_time

            self.finalize_campaign(success, campaign_delay, duration)
        else:
            self.logger.info(
                f'Campaign could not be initiated due to the following issues {", ".join(campaign_init["errors"])}'
            )

            if self.campaign.status != Campaign.STARTING:
                self.campaign.status = Campaign.STOPPING
                self.campaign.save(update_fields=["status"])

            self.check_proxy_in()

        self.logger.info("Campaign ended")


class ManageCampaignsTask(Task):
    def __init__(self):
        self.soft_time_limit = 240
        self.time_limit = 450
        self.logger = logging.getLogger(__name__)

    def get_available_proxy(self):
        proxies = Proxy.objects.filter(is_active=True)
        in_use_proxies = Proxy.objects.filter(checked_out_by__isnull=False).values_list(
            "id", flat=True
        )

        for proxy in proxies:
            if proxy.id not in in_use_proxies and not proxy.checked_out_by:
                return proxy

            runtime = (
                (timezone.now() - proxy.checkout_time).total_seconds()
                if proxy.checkout_time is not None
                else None
            )
            if (
                runtime
                and proxy.checked_out_by
                and runtime > CampaignTask.soft_time_limit
            ):
                try:
                    campaign = Campaign.objects.get(id=proxy.checked_out_by)
                    if runtime > CampaignTask.soft_time_limit * 1.5:
                        self.logger.warning(
                            f"Campaign has been running for {runtime} sec, checking in."
                        )
                        proxy.check_in()
                        campaign.status = Campaign.STARTING
                        campaign.save()
                except Campaign.DoesNotExist:
                    self.logger.warning("Campaign does not exist. Checking in.")
                    proxy.check_in()

    def start_campaign(self, campaign, proxy=None):
        if proxy:
            try:
                proxy.check_out(campaign.id)

                campaign.status = Campaign.IN_QUEUE
                campaign.queue_status = "N/A"

                campaign.save(update_fields=["status", "queue_status"])

                CampaignTask.delay(campaign.id, proxy_id=proxy.id)
                self.logger.info(
                    f"Campaign Started: {campaign.title} for {campaign.posh_user.username} with {proxy.license_id} proxy"
                )

                return True
            except ValueError:
                self.logger.warning(f"Proxy: {proxy} already in use")

                return False
        else:
            campaign.status = Campaign.IN_QUEUE
            campaign.queue_status = "N/A"
            campaign.save(update_fields=["status", "queue_status"])

            CampaignTask.delay(campaign.id)

            self.logger.info(
                f"Campaign Started: {campaign.title} for {campaign.posh_user.username} with no device and no proxy"
            )

            return True

    def run(self, *args, **kwargs):
        now = timezone.now()
        campaigns = Campaign.objects.filter(
            Q(status__in=[Campaign.STOPPING, Campaign.IDLE, Campaign.STARTING])
            & (Q(next_runtime__lte=now) | Q(next_runtime__isnull=True))
        ).order_by("next_runtime")
        queue_num = 1
        check_for_proxy = True

        for campaign in campaigns:
            campaign_started = False
            available_proxy = None

            need_to_list = ListedItem.objects.filter(
                posh_user=campaign.posh_user, status=ListedItem.NOT_LISTED
            ).exists()

            if (
                campaign.posh_user
                and check_for_proxy
                and (need_to_list or not campaign.posh_user.is_registered)
            ):
                available_proxy = self.get_available_proxy()

            if (
                campaign.status == Campaign.STOPPING
                or not campaign.posh_user
                or not campaign.posh_user.is_active
                or not campaign.posh_user.is_active_in_posh
            ):
                campaign.status = Campaign.STOPPED
                campaign.queue_status = "N/A"
                campaign.next_runtime = None

                campaign.save(update_fields=["status", "queue_status", "next_runtime"])
            elif campaign.status == Campaign.IDLE and campaign.next_runtime is not None:
                campaign_started = self.start_campaign(campaign, available_proxy)
            elif campaign.status == Campaign.STARTING and (
                available_proxy
                or (not need_to_list and campaign.posh_user.is_registered)
            ):
                campaign_started = self.start_campaign(campaign, available_proxy)

            if (not campaign_started and campaign.status == Campaign.STARTING) or (
                not available_proxy and campaign.status == Campaign.STARTING
            ):
                campaign.queue_status = str(queue_num)
                campaign.save(update_fields=["queue_status"])
                queue_num += 1

                if check_for_proxy:
                    check_for_proxy = False

        try:
            redis_client = caches["default"].client.get_client()
            redis_client.delete(f"{self.name}")
        except Exception as e:
            self.logger.error(e)


class CheckPoshUsers(Task):
    @staticmethod
    def check_user_active(soup):
        class_name = "m--t--9"
        text_content = "No listings found."
        message_element = soup.find("div", {"class": class_name, "style": "display:;"})

        if message_element and message_element.get_text(strip=True) == text_content:
            listings_count_element = soup.find(
                "span", {"data-test": "closet_listings_count"}
            )

            listings_count = int(listings_count_element.get_text(strip=True))
            if listings_count > 1:
                return False

        return True

    @staticmethod
    def get_user_listings(soup):
        listings = []
        listing_container_class = "card--small"

        listing_elements = soup.find_all("div", {"class": listing_container_class})

        for listing_element in listing_elements:
            title_element = listing_element.find("a", {"class": "tile__title"})
            status_element = listing_element.find("i", {"class": "tile__inventory-tag"})
            status = ListedItem.UP

            if status_element:
                posh_status = (
                    status_element.find("span", class_="inventory-tag__text")
                    .get_text(strip=True)
                    .lower()
                )
                posh_status = posh_status.replace(" ", "")

                if posh_status == "notforsale":
                    status = ListedItem.NOT_FOR_SALE
                elif posh_status == "sold":
                    status = ListedItem.SOLD
                elif posh_status == "reserved":
                    status = ListedItem.RESERVED

            listings.append(
                {
                    "id": title_element["data-et-prop-listing_id"],
                    "title": title_element.get_text(strip=True),
                    "status": status,
                }
            )

        return listings

    @staticmethod
    def process_listed_item(
        listed_item: ListedItem, posh_listed_item: Union[dict, None]
    ):
        if not posh_listed_item and listed_item.status != ListedItem.UNDER_REVIEW:
            listed_item.status = ListedItem.REMOVED
            listed_item.datetime_removed = timezone.now()

            listed_item.save(update_fields=["status", "datetime_removed"])
        elif posh_listed_item:
            if not listed_item.listed_item_id:
                listed_item.listed_item_id = posh_listed_item["id"]
                listed_item.save(update_fields=["listed_item_id"])

            if (
                posh_listed_item["status"] == ListedItem.SOLD
                and listed_item.datetime_sold is None
            ):
                listed_item.datetime_sold = timezone.now()
                listed_item.status = ListedItem.SOLD

                listed_item.save(update_fields=["status", "datetime_sold"])
            elif (
                posh_listed_item["status"] == ListedItem.RESERVED
                and listed_item.status != ListedItem.RESERVED
            ):
                listed_item.status = ListedItem.RESERVED

                listed_item.save(update_fields=["status"])
            elif (
                posh_listed_item["status"] == ListedItem.UP
                and listed_item.status == ListedItem.RESERVED
            ):
                listed_item.status = ListedItem.UP

                listed_item.save(update_fields=["status"])
            elif (
                posh_listed_item["status"] == ListedItem.UP
                and listed_item.status == ListedItem.UNDER_REVIEW
            ):
                try:
                    campaign = Campaign.objects.get(posh_user=listed_item.posh_user)

                    if campaign.status == Campaign.PAUSED:
                        campaign.status = Campaign.STARTING
                        campaign.next_runtime = timezone.now() + datetime.timedelta(
                            seconds=60
                        )

                        campaign.save(update_fields=["status", "next_runtime"])
                except Campaign.DoesNotExist:
                    pass

                listed_item.status = ListedItem.UP

                if not listed_item.datetime_passed_review:
                    listed_item.datetime_passed_review = timezone.now()

                listed_item.save(update_fields=["status", "datetime_passed_review"])
            elif (
                posh_listed_item["status"] == ListedItem.NOT_FOR_SALE
                and listed_item.status != ListedItem.NOT_FOR_SALE
            ):
                listed_item.status = ListedItem.NOT_FOR_SALE
                listed_item.save(update_fields=["status"])

    def get_user_profile(self, username: str) -> dict:
        profile = {}
        profile_url = f"https://poshmark.com/closet/{username}"
        response = requests.get(profile_url)

        if response.status_code == 200:
            profile["username"] = username
            soup = BeautifulSoup(response.content, "html.parser")
            is_active = self.check_user_active(soup)

            profile["is_active"] = is_active

            if is_active:
                profile["listings"] = self.get_user_listings(soup)

        return profile

    def run(self, username: Union[str, None] = None):
        excluded_statuses = (
            ListedItem.REDEEMABLE,
            ListedItem.REDEEMED,
            ListedItem.REMOVED,
            ListedItem.SHIPPED,
            ListedItem.CANCELLED,
            ListedItem.NOT_LISTED,
        )
        posh_users = PoshUser.objects.filter(
            is_active_in_posh=True, is_registered=True, user__is_active=True
        )

        if username:
            posh_users = posh_users.filter(username=username)

        for posh_user in posh_users:
            profile = self.get_user_profile(posh_user)
            if profile:
                listed_items = posh_user.listeditem_set.exclude(
                    status__in=excluded_statuses
                )

                if profile["is_active"]:
                    # Process all the listings the bot currently knows about with ids
                    for listed_item in listed_items.exclude(listed_item_id=""):
                        if profile["listings"]:
                            posh_listed_item = next(
                                (
                                    listing
                                    for listing in profile["listings"]
                                    if listing["id"] == listed_item.listed_item_id
                                ),
                                None,
                            )
                        else:
                            posh_listed_item = None

                        self.process_listed_item(listed_item, posh_listed_item)

                        # Remove the already processed item
                        if posh_listed_item:
                            profile["listings"] = [
                                listing
                                for listing in profile["listings"]
                                if listing["id"] != posh_listed_item["id"]
                            ]

                    # Process all the listings the bot currently knows about without ids
                    for listed_item in listed_items.filter(listed_item_id=""):
                        if profile["listings"]:
                            posh_listed_item = next(
                                (
                                    listing
                                    for listing in profile["listings"]
                                    if listing["title"] == listed_item.listing_title
                                ),
                                None,
                            )
                        else:
                            posh_listed_item = None

                        self.process_listed_item(listed_item, posh_listed_item)

                        # Remove the already processed item
                        if posh_listed_item:
                            profile["listings"] = [
                                listing
                                for listing in profile["listings"]
                                if listing["id"] != posh_listed_item["id"]
                            ]

                    for listed_item in profile.get("listings", []):
                        if not ListedItem.objects.filter(
                            listed_item_id=listed_item["id"]
                        ).exists():
                            try:
                                listing = Listing.objects.get(
                                    title=listed_item["title"]
                                )
                            except Listing.DoesNotExist:
                                listing = None
                            except Listing.MultipleObjectsReturned:
                                listing = None

                            ListedItem.objects.create(
                                posh_user=posh_user,
                                listing_title=listed_item["title"],
                                listing=listing,
                                listed_item_id=listed_item["id"],
                                status=listed_item["status"],
                                datetime_sold=timezone.now()
                                if listed_item["status"] == ListedItem.SOLD
                                else None,
                            )
                else:
                    try:
                        campaign = Campaign.objects.get(posh_user=posh_user)
                        campaign.status = Campaign.STOPPING

                        campaign.save(update_fields=["status"])
                    except Campaign.DoesNotExist:
                        pass

                    posh_user.is_active_in_posh = False
                    posh_user.date_disabled = timezone.now().date()
                    posh_user.save(update_fields=["is_active_in_posh", "date_disabled"])

                    for listed_item in listed_items:
                        listed_item.status = ListedItem.REMOVED
                        listed_item.datetime_removed = timezone.now()

                        listed_item.save(update_fields=["status", "datetime_removed"])

        try:
            redis_client = caches["default"].client.get_client()
            redis_client.delete(f"{self.name}")
        except Exception:
            pass


CampaignTask = app.register_task(CampaignTask())
ManageCampaignsTask = app.register_task(ManageCampaignsTask())
CheckPoshUsers = app.register_task(CheckPoshUsers())


@shared_task
def posh_user_cleanup():
    month_ago = (timezone.now() - datetime.timedelta(days=30)).date()

    # Get all posh_users who have been inactive for at least a day
    posh_users = PoshUser.objects.filter(
        is_active=False, date_disabled__lt=month_ago
    ).exclude(
        listeditem__status__in=(
            ListedItem.SOLD,
            ListedItem.REDEEMED_PENDING,
            ListedItem.REDEEMABLE,
            ListedItem.SHIPPED,
            ListedItem,
        )
    )

    posh_users.delete()

    try:
        redis_client = caches["default"].client.get_client()
        redis_client.delete(f"{posh_user_cleanup.name}")
    except Exception:
        pass


@shared_task
def send_support_emails():
    logger = logging.getLogger(__name__)
    smtp_server = "smtp.mail.yahoo.com"
    smtp_port = 587
    posh_users = PoshUser.objects.filter(is_active=True, send_support_email=True)
    all_email_info = PaymentEmailContent.objects.all()
    recipients = ["support@yahoo.com", "hello@poshmark.com"]

    if all_email_info:
        for posh_user in posh_users:
            if posh_user.email and posh_user.email_imap_password:
                email_info: PaymentEmailContent = random.choice(all_email_info)
                body = email_info.body
                body = body.replace("{{user_name}}", posh_user.username)
                body = body.replace("{{email}}", posh_user.email)

                # Check if last support email was sent at least 24 hours ago
                if not posh_user.date_last_support_email or (
                    timezone.now() - posh_user.date_last_support_email
                ) >= datetime.timedelta(hours=24):
                    # Randomly decide whether to send an email (25% chance)
                    if random.random() <= 0.16:
                        msg = MIMEMultipart()
                        msg["From"] = posh_user.email
                        msg["To"] = ", ".join(recipients)
                        msg["Subject"] = email_info.subject
                        msg.attach(MIMEText(body, "plain"))

                        try:
                            # Connect to the SMTP server
                            with smtplib.SMTP(smtp_server, smtp_port) as server:
                                server.starttls()
                                server.login(
                                    posh_user.email, posh_user.email_imap_password
                                )

                                # Send the email
                                server.sendmail(
                                    posh_user.email, recipients, msg.as_string()
                                )
                                logger.info("Email sent successfully!")

                                # Update the date_last_support_email field
                                posh_user.date_last_support_email = timezone.now()
                                posh_user.save()

                        except Exception as e:
                            logger.error("An error occurred", exc_info=True)

    try:
        redis_client = caches["default"].client.get_client()
        redis_client.delete(f"{send_support_emails.name}")
    except Exception:
        pass


@shared_task
def check_listed_items(username: str = ""):
    logger = logging.getLogger(__name__)
    sold_items = ListedItem.objects.filter(
        datetime_sold__isnull=False, datetime_shipped__isnull=True
    )

    if username:
        sold_items = sold_items.filter(posh_user__username=username)

    for item in sold_items:
        listing_title = item.listing_title
        posh_user = item.posh_user
        sold_time = item.datetime_sold

        # Check if the PoshUser has the necessary IMAP email password
        if posh_user.email and posh_user.email_imap_password:
            email_address = posh_user.email
            password = posh_user.email_imap_password

            # Construct the subject keyword with dynamic values
            subject_keyword = f'Here is your shipping label for "{listing_title}"'

            matching_email = zke_yahoo.check_for_email(
                "orders@poshmark.com",
                email_address,
                password,
                subject_keyword,
                sold_time,
            )

            if matching_email:
                for part in matching_email.walk():
                    if part.get_content_type() == "text/html":
                        body = part.get_payload(decode=True)
                        if isinstance(body, bytes):
                            body = body.decode("utf-8")
                            soup = BeautifulSoup(body, "html.parser")

                            earnings_td = soup.find(
                                "td", string="Your Earnings (minus fee)"
                            )
                            if earnings_td:
                                # Get the next sibling <td> element which contains the earnings amount
                                earnings_amount_td = earnings_td.find_next(
                                    "td", style="text-align:right;"
                                )
                                if earnings_amount_td:
                                    earnings_amount = earnings_amount_td.get_text(
                                        strip=True
                                    )
                                    item.earnings = Decimal(earnings_amount.strip("$"))

                date_received_str = matching_email.get("Date")
                date_received = datetime.datetime.strptime(
                    date_received_str, "%a, %d %b %Y %H:%M:%S %z (%Z)"
                )
                item.status = ListedItem.SHIPPED
                item.datetime_shipped = date_received.astimezone(
                    pytz.timezone("US/Eastern")
                )
                item.save()

                logger.info(f"{posh_user} - Updated {item} to SHIPPED")

    shipped_items = ListedItem.objects.filter(
        datetime_shipped__isnull=False, datetime_redeemable__isnull=True
    )

    if username:
        shipped_items = shipped_items.filter(posh_user__username=username)

    for item in shipped_items:
        listing_title = item.listing_title
        posh_user = item.posh_user
        sold_time = item.datetime_sold

        # Check if the PoshUser has the necessary IMAP email password
        if posh_user.email and posh_user.email_imap_password:
            email_address = posh_user.email
            password = posh_user.email_imap_password

            # Construct the subject keyword with dynamic values
            subject_keyword = f'Your earnings from "{listing_title}"'

            matching_email = zke_yahoo.check_for_email(
                "orders@poshmark.com",
                email_address,
                password,
                subject_keyword,
                sold_time,
            )

            if matching_email:
                date_format = "%m/%d/%Y %I:%M %p %Z"
                date_received_str = matching_email.get("Date")
                date_received = datetime.datetime.strptime(
                    date_received_str, "%a, %d %b %Y %H:%M:%S %z (%Z)"
                ).astimezone(pytz.timezone("US/Eastern"))

                message = (
                    f"Item: {item.listing_title}\n"
                    f"Date of Email: {date_received.strftime(date_format)}\n"
                    f"Posh Username: {item.posh_user.username}\n"
                    f"Posh Password: {item.posh_user.password}\n"
                    f"Email: {item.posh_user.email}\n"
                    f"Email IMAP Password: {item.posh_user.email_imap_password}\n"
                )

                item.status = ListedItem.REDEEMABLE
                item.datetime_redeemable = date_received
                item.save()

                logger.info(f"{posh_user} - Updated {item} to REDEEMABLE")
                if item.posh_user.user.email:
                    email_credentials = json.loads(os.environ["EMAIL_CREDENTIALS"])
                    from_email = email_credentials["username"]
                    password = email_credentials["password"]
                    to_email = [item.posh_user.user.email]
                    subject = (
                        f"New Sale Available to Redeem for {item.posh_user.username}"
                    )
                    send_email.delay(from_email, password, to_email, subject, message)

                    logger.info("Email sent to queue")
                else:
                    logger.info(f"Email not sent: {item.posh_user.user.email}")

    redeemable_items = ListedItem.objects.filter(
        datetime_redeemable__isnull=False, datetime_redeemed__isnull=True
    )

    if username:
        redeemable_items = redeemable_items.filter(posh_user__username=username)

    for item in redeemable_items:
        posh_user = item.posh_user
        redeemable_time = item.datetime_redeemed

        # Check if the PoshUser has the necessary IMAP email password
        if posh_user.email and posh_user.email_imap_password:
            email_address = posh_user.email
            password = posh_user.email_imap_password

            possible_subjects = [
                "Your Instant Transfer request has been received",
                "Your request for direct deposit has been received",
            ]

            for subject_keyword in possible_subjects:
                matching_email = zke_yahoo.check_for_email(
                    "support@poshmark.com",
                    email_address,
                    password,
                    subject_keyword,
                    redeemable_time,
                )

                if matching_email:
                    date_received_str = matching_email.get("Date")
                    date_received = datetime.datetime.strptime(
                        date_received_str, "%a, %d %b %Y %H:%M:%S %z (%Z)"
                    ).astimezone(pytz.timezone("US/Eastern"))

                    if "instant transfer" in matching_email.get("Subject").lower():
                        status = ListedItem.REDEEMED
                    else:
                        status = ListedItem.REDEEMED_PENDING

                    item.status = status
                    item.datetime_redeemed = date_received
                    item.save()

                    logger.info(f"{posh_user} - Updated {item} to {status}")

                    break

    under_review_items = ListedItem.objects.filter(
        datetime_listed__isnull=False,
        datetime_passed_review__isnull=True,
        datetime_removed__isnull=True,
    )

    if username:
        under_review_items = under_review_items.filter(posh_user__username=username)

    for item in under_review_items:
        posh_user = item.posh_user
        try:
            campaign = item.posh_user.campaign
        except Campaign.DoesNotExist:
            campaign = None
        datetime_listed = item.datetime_listed

        # Check if the PoshUser has the necessary IMAP email password
        if posh_user.email and posh_user.email_imap_password:
            email_address = posh_user.email
            password = posh_user.email_imap_password

            matching_email = zke_yahoo.check_for_email(
                "support@poshmark.com",
                email_address,
                password,
                f'Your Poshmark listing "{item.listing_title}" has been removed due to Counterfeit item(s)',
                datetime_listed,
            )

            if matching_email:
                date_received_str = matching_email.get("Date")
                date_received = datetime.datetime.strptime(
                    date_received_str, "%a, %d %b %Y %H:%M:%S %z (%Z)"
                ).astimezone(pytz.timezone("US/Eastern"))

                item.status = ListedItem.REMOVED
                item.datetime_removed = date_received
                item.save()

                logger.info(f"{posh_user} - Updated {item} to REMOVED")

                if (
                    campaign
                    and campaign.status == Campaign.PAUSED
                    and not campaign.posh_user.listeditem_set.filter(
                        status__in=(
                            ListedItem.UP,
                            ListedItem.UNDER_REVIEW,
                            ListedItem.RESERVED,
                        )
                    ).exists()
                ):
                    campaign.status = Campaign.STOPPING
                    campaign.save()

    try:
        redis_client = caches["default"].client.get_client()
        redis_client.delete(f"{check_listed_items.name}")
    except Exception:
        pass


@shared_task
def send_email(
    from_email: str, password: str, to_email: list, subject: str, message: str
):
    email = EmailMessage()
    email["From"] = from_email
    email["To"] = to_email
    email["Subject"] = subject
    email.set_content(message)

    context = ssl.create_default_context()

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
        smtp.login(from_email, password)
        smtp.sendmail(from_email, to_email, email.as_string())


@shared_task
def test_task():
    logger = logging.getLogger(__name__)
    logger.info("TEst success")
