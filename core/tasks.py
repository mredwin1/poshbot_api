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

from bs4 import BeautifulSoup
from celery import shared_task, Task
from celery.signals import task_prerun, task_postrun
from celery.beat import Scheduler
from decimal import Decimal
from django.core.cache import caches
from django.db.models import Q
from django.utils import timezone
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from requests.exceptions import ConnectionError
from typing import Union, Dict, List

from chrome_clients.clients import PoshmarkClient, OctoAPIClient
from chrome_clients.errors import (
    LoginOrRegistrationError,
    UserDisabledError,
    ShareError,
    ListingNotFoundError,
    NoLikesError,
    NotLoggedInError,
    NoActiveOffersError,
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


class PoshmarkTask(Task):
    def __init__(self):
        self.soft_time_limit = 600
        self.time_limit = 800
        self.loop = None

    @staticmethod
    def get_octo_profile(proxy: Union[Dict, None], octo_details: Union[Dict, None]):
        octo_client = OctoAPIClient()
        proxy_uuid = ""

        if proxy is not None:
            proxies = octo_client.get_proxies(external_id=proxy["external_id"])

            if proxies:
                current_proxy = proxies[0]

                proxy_differences = {}
                for key, value in proxy.items():
                    if value != current_proxy[key]:
                        proxy_differences[key] = value

                if proxy_differences:
                    proxy = octo_client.update_proxy(proxy["uuid"], proxy_differences)
            else:
                proxy = octo_client.create_proxy(proxy)

            proxy_uuid = proxy["uuid"]

        if not octo_details.get("uuid"):
            if proxy:
                profile_uuid = octo_client.create_profile(
                    octo_details["title"],
                    octo_details["tags"],
                    proxy_uuid=octo_details["uuid"],
                )
            else:
                profile_uuid = octo_client.create_profile(
                    octo_details["title"], octo_details["tags"]
                )
            profile = octo_client.get_profile(profile_uuid)

        else:
            profile = octo_client.get_profile(octo_details["uuid"])

        if proxy:
            octo_client.update_profile(profile["uuid"], proxy_uuid=proxy_uuid)
            profile["proxy"] = proxy
        elif not proxy and profile["proxy"]:
            octo_client.update_profile(profile["uuid"])

        return profile

    @staticmethod
    def start_profile(profile: Dict):
        octo_client = OctoAPIClient()
        width, height = map(
            int, profile["fingerprint"]["screen"].split(" ")[0].split("x")
        )

        runtime_details = octo_client.start_profile(profile["uuid"])
        runtime_details["width"] = width
        runtime_details["height"] = height

        ws_endpoint = runtime_details["ws_endpoint"]
        ws_endpoint = ws_endpoint.replace("127.0.0.1", os.environ["OCTO_ENDPOINT"])
        runtime_details["ws_endpoint"] = ws_endpoint

        return runtime_details

    @staticmethod
    async def register(client: PoshmarkClient, details: Dict, logger: logging.Logger):
        try:
            username = await client.register(details)

            posh_user = await PoshUser.objects.aget(id=details["posh_user_id"])
            if username != details["username"]:
                octo_client = OctoAPIClient()
                octo_client.update_profile(
                    details["octo_details"]["uuid"], title=username
                )
                posh_user.username = username
                posh_user.is_registered = True
                await posh_user.asave(update_fields=["username", "is_registered"])
            else:
                posh_user.is_registered = True
                await posh_user.asave(update_fields=["is_registered"])
            await client.finish_registration(details)

        except LoginOrRegistrationError as e:
            logger.error(e)

            if "form__error" in str(e):
                logger.warning(f"Setting user {details['username']} inactive")
                posh_user = await PoshUser.objects.aget(id=details["posh_user_id"])
                posh_user.is_active_in_posh = False
                posh_user.datetime_disabled = timezone.now()
                await posh_user.asave(
                    update_fields=["is_active_in_posh", "datetime_disabled"]
                )

    @staticmethod
    async def list_items(client: PoshmarkClient, details: Dict, logger: logging.Logger):
        for item_to_list in details["items"]:
            try:
                listed_item = await client.list_item(details["user_info"], item_to_list)
                item_to_list_obj = ListedItem.objects.aget(id=item_to_list["id"])
                await item_to_list_obj.aupdate(
                    status=ListedItem.UNDER_REVIEW,
                    listed_item_id=listed_item["listing_id"],
                    datetime_listed=timezone.now(),
                )

            except UserDisabledError as e:
                logger.error(e)
                posh_user = await PoshUser.objects.aget(id=details["posh_user_id"])
                posh_user.is_active_in_posh = False
                posh_user.datetime_disabled = timezone.now()
                await posh_user.asave(
                    update_fields=["is_active_in_posh", "datetime_disabled"]
                )

    @staticmethod
    async def share_listings(
        client: PoshmarkClient, details: Dict, logger: logging.Logger
    ):
        for item_to_share in details["items"]:
            try:
                await client.share_listing(details["user_info"], item_to_share)
            except (ListingNotFoundError, ShareError) as e:
                logger.warning(e)

    @staticmethod
    async def check_comments(
        client: PoshmarkClient, details: Dict, logger: logging.Logger
    ):
        for item_to_check_comments in details["items"]:
            try:
                await client.check_comments(
                    details["user_info"], item_to_check_comments, details["bad_phrases"]
                )
            except ListingNotFoundError as e:
                logger.warning(e)

    @staticmethod
    async def send_offers(
        client: PoshmarkClient, details: Dict, logger: logging.Logger
    ):
        for item_to_send_offers in details["items"]:
            try:
                await client.send_offers_to_likers(
                    details["user_info"],
                    item_to_send_offers["listing_id"],
                    item_to_send_offers["offer"],
                )
            except (NoLikesError, ListingNotFoundError) as e:
                logger.warning(e)

    @staticmethod
    async def check_offers(
        client: PoshmarkClient, details: Dict, logger: logging.Logger
    ):
        for item_to_check_offers in details["items"]:
            try:
                await client.check_offers(
                    details["user_info"],
                    item_to_check_offers["listing_id"],
                    item_to_check_offers["lowest_price"],
                )
            except (NoActiveOffersError, ListingNotFoundError) as e:
                logger.warning(e)

    @staticmethod
    async def like_follow_share(client: PoshmarkClient, details: Dict):
        await client.like_follow_share(details["user_info"])

    async def _run(self, actions: Dict, runtime_details: Dict, logger: logging.Logger):
        ws_endpoint = runtime_details["ws_endpoint"]
        width = runtime_details["width"]
        height = runtime_details["height"]
        async with PoshmarkClient(ws_endpoint, width, height, logger) as client:
            for action_name, action_details in actions.items():
                action_method = getattr(self, action_name)
                start_time = time.perf_counter()
                await action_method(client, action_details, logger)
                end_time = time.perf_counter()
                elapsed_time = end_time - start_time
                logger.info(
                    f"Time to {action_name} for {action_details['user_info']['username']}: {elapsed_time}"
                )

    def run(self, task_blueprint: Dict, proxy: Union[Dict, None] = None):
        task_start_time = time.perf_counter()
        campaign = Campaign.objects.get(id=task_blueprint["campaign_id"])
        campaign.status = Campaign.RUNNING
        campaign.next_runtime = timezone.now()
        campaign.save(update_fields=["status", "next_runtime"])

        if proxy:
            proxy_obj = Proxy.objects.get(id=proxy["id"])
            proxy_obj.checkout_time = timezone.now()
            proxy_obj.save(update_fields=["checkout_time"])

        octo_profile_details = task_blueprint["octo_details"]
        octo_profile_details = self.get_octo_profile(proxy, octo_profile_details)
        runtime_details = self.start_profile(octo_profile_details)
        logger = logging.getLogger(__name__)

        loop = self.loop
        try:
            loop.run_until_complete(
                self._run(task_blueprint["actions"], runtime_details, logger)
            )
        except Exception as e:
            logger.error(f"An error occurred: {e}")

        task_end_time = time.perf_counter()
        total_runtime = task_end_time - task_start_time

        delay = task_blueprint["delay"] - total_runtime

        if delay < 0:
            delay = task_blueprint["delay"]

        next_runtime = timezone.now() + datetime.timedelta(seconds=delay)

        campaign.status = Campaign.IDLE
        campaign.next_runtime = next_runtime
        campaign.save(update_fields=["status", "next_runtime"])
        username = list(task_blueprint["actions"].values())[0]["user_info"]["username"]
        logger.info(
            f"Time to finish_task for {username}: {total_runtime}. Starting back up in {delay} seconds"
        )


class ManageCampaignsTask(Task):
    def __init__(self):
        self.soft_time_limit = 240
        self.time_limit = 450
        self.logger = logging.getLogger(__name__)

    def inspect_active_profiles(self):
        try:
            octo_client = OctoAPIClient()

            response = octo_client.get_active_profiles()

            if "error" in response:
                self.logger.warning(f"Error while getting active profiles: {response}")

                return

            current_time = timezone.now().timestamp()
            for profile in response:
                start_time = profile.get("start_time")

                if start_time is None:
                    start_time = current_time

                seconds_since_start = current_time - start_time

                if seconds_since_start > PoshmarkTask.soft_time_limit + 30:
                    response = octo_client.stop_profile(profile["uuid"])
                    self.logger.debug(f"Stopping profile {profile['uuid']}: {response}")
        except ConnectionError:
            self.logger.error("Error while connecting to octo endpoint")

    def get_available_proxies(self) -> List[Proxy]:
        bad_checkout_time = timezone.now() - datetime.timedelta(
            seconds=PoshmarkTask.soft_time_limit
        )
        proxies = Proxy.objects.filter(is_active=True).filter(
            Q(checked_out_by__isnull=True) | Q(checkout_time__lte=bad_checkout_time)
        )
        available_proxies = []

        for proxy in proxies:
            if not proxy.checked_out_by:
                available_proxies.append(proxy)

            runtime = (
                (timezone.now() - proxy.checkout_time).total_seconds()
                if proxy.checkout_time
                else None
            )
            if not runtime or runtime > PoshmarkTask.soft_time_limit + 30:
                try:
                    campaign = Campaign.objects.get(id=proxy.checked_out_by)

                    if campaign.posh_user and campaign.posh_user.octo_uuid:
                        octo_client = OctoAPIClient()
                        octo_client.stop_profile(campaign.posh_user.octo_uuid)

                    self.logger.warning(
                        f"Campaign has been running for {runtime} sec, checking in."
                    )
                    proxy.check_in()
                    campaign.status = Campaign.STARTING
                    campaign.save()
                except Campaign.DoesNotExist:
                    self.logger.warning("Campaign does not exist. Checking in.")
                    proxy.check_in()

        return available_proxies

    def run(self, *args, **kwargs):
        try:
            octo_client = OctoAPIClient()
            octo_client.check_username()
        except NotLoggedInError as e:
            self.logger.error(str(e))
            return False
        except ConnectionError:
            self.logger.error("Error while connecting to octo endpoint")
            return False

        now = timezone.now()
        campaigns = (
            Campaign.objects.filter(
                Q(
                    status__in=(
                        Campaign.STOPPING,
                        Campaign.IDLE,
                        Campaign.STARTING,
                        Campaign.RUNNING,
                        Campaign.IN_QUEUE,
                    )
                )
                & (Q(next_runtime__lte=now) | Q(next_runtime__isnull=True))
            )
            .order_by("next_runtime")
            .select_related("posh_user")
        )
        queue_num = 1

        self.inspect_active_profiles()
        available_proxies = self.get_available_proxies()

        for campaign in campaigns:
            if (
                campaign.status == Campaign.STOPPING
                or not campaign.next_runtime
                or not campaign.posh_user
                or not campaign.posh_user.is_active
                or not campaign.posh_user.is_active_in_posh
            ):
                campaign.status = Campaign.STOPPED
                campaign.queue_status = "N/A"
                campaign.next_runtime = None
                campaign.save(update_fields=["status", "queue_status", "next_runtime"])
                continue

            # If campaign has been running for too long just reset it so it runs again
            max_runtime = campaign.next_runtime + datetime.timedelta(
                seconds=PoshmarkTask.soft_time_limit + 60
            )
            if now > max_runtime:
                campaign.status = Campaign.STARTING
                campaign.queue_status = "CALCULATING"
                campaign.next_runtime = now
                campaign.save(update_fields=["status", "queue_status", "next_runtime"])
                continue

            task_blueprint = campaign.posh_user.task_blueprint
            register_or_list = (
                "register" in task_blueprint["actions"]
                or "list_items" in task_blueprint["actions"]
            )
            if (
                register_or_list
                and available_proxies
                and campaign.status not in (Campaign.RUNNING, Campaign.IN_QUEUE)
            ):
                proxy = available_proxies.pop()
                ip_reset = proxy.reset_ip()
                if ip_reset:
                    self.logger.info(ip_reset)
                    proxy.check_out(campaign.id)

                    campaign.status = Campaign.IN_QUEUE
                    campaign.queue_status = "N/A"
                    campaign.save(update_fields=["status", "queue_status"])
                    PoshmarkTask.delay(task_blueprint, proxy.proxy_info)
                    self.logger.info(
                        f"Campaign Started: {campaign.title} for {campaign.posh_user.username} with {proxy} proxy"
                    )
                else:
                    self.logger.warning(f"Could not reset IP: {ip_reset}")
            elif (
                register_or_list
                and not available_proxies
                and campaign.status not in (Campaign.RUNNING, Campaign.IN_QUEUE)
            ):
                campaign.status = Campaign.STARTING
                campaign.queue_status = str(queue_num)
                campaign.save(update_fields=["status", "queue_status"])
                queue_num += 1
            elif (
                not register_or_list
                and task_blueprint["actions"]
                and campaign.status not in (Campaign.RUNNING, Campaign.IN_QUEUE)
            ):
                campaign.status = Campaign.IN_QUEUE
                campaign.queue_status = "N/A"
                campaign.save(update_fields=["status", "queue_status"])
                PoshmarkTask.delay(task_blueprint)
                self.logger.info(
                    f"Campaign Started: {campaign.title} for {campaign.posh_user.username}"
                )
            elif not task_blueprint["actions"] and campaign.status not in (
                Campaign.RUNNING,
                Campaign.IN_QUEUE,
            ):
                timeframe = timezone.now() - datetime.timedelta(hours=24)
                all_listed_items = ListedItem.objects.filter(
                    posh_user=campaign.posh_user
                )
                under_review_listed_items = all_listed_items.filter(
                    status=ListedItem.UNDER_REVIEW
                ).exists()
                removed_listed_items = all_listed_items.filter(
                    datetime_removed__gte=timeframe
                ).exists()
                sold_listed_items = all_listed_items.filter(
                    datetime_sold__gte=timeframe
                ).exists()

                if under_review_listed_items:
                    self.logger.info(
                        f"{campaign.posh_user} has nothing to do but a listing under review. Pausing campaign."
                    )
                    campaign.status = Campaign.PAUSED
                    campaign.next_runtime = None
                    campaign.queue_status = "N/A"
                    campaign.save(
                        update_fields=["status", "next_runtime", "queue_status"]
                    )
                elif removed_listed_items:
                    self.logger.info(
                        f"{campaign.posh_user} has nothing to do and only removed listings in the last 24 hours. Stopping campaign."
                    )
                    campaign.status = Campaign.STOPPING
                    campaign.next_runtime = None
                    campaign.queue_status = "N/A"
                    campaign.save(
                        update_fields=["status", "next_runtime", "queue_status"]
                    )
                elif sold_listed_items:
                    self.logger.info(
                        f"{campaign.posh_user} has nothing to do and only sold listings in the last 24 hours. Stopping campaign."
                    )
                    campaign.status = Campaign.STOPPING
                    campaign.next_runtime = None
                    campaign.queue_status = "N/A"
                    campaign.save(
                        update_fields=["status", "next_runtime", "queue_status"]
                    )

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
            if listings_count >= 1:
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
                    posh_user.datetime_disabled = timezone.now()
                    posh_user.save(
                        update_fields=["is_active_in_posh", "datetime_disabled"]
                    )

                    for listed_item in listed_items:
                        listed_item.status = ListedItem.REMOVED
                        listed_item.datetime_removed = timezone.now()

                        listed_item.save(update_fields=["status", "datetime_removed"])

        try:
            redis_client = caches["default"].client.get_client()
            redis_client.delete(f"{self.name}")
        except Exception:
            pass


PoshmarkTask = app.register_task(PoshmarkTask())
ManageCampaignsTask = app.register_task(ManageCampaignsTask())
CheckPoshUsers = app.register_task(CheckPoshUsers())


@task_prerun.connect(sender=PoshmarkTask)
def start_event_loop(*args, **kwargs):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    kwargs["task"].loop = loop


@task_postrun.connect(sender=PoshmarkTask)
def close_event_loop(*args, **kwargs):
    loop = kwargs["task"].loop

    if loop and not loop.is_closed():
        # Cancel all pending tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass

        # Shutdown async generators
        loop.run_until_complete(loop.shutdown_asyncgens())

        # Close the loop
        loop.close()


@shared_task
def posh_user_cleanup():
    month_ago = timezone.now() - datetime.timedelta(days=30)

    # Get all posh_users who have been inactive for at least a day
    posh_users = PoshUser.objects.filter(
        is_active=False, datetime_disabled__lt=month_ago
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
def profile_cleanup():
    timeframe = timezone.now() - datetime.timedelta(hours=12)

    # Get all posh_users who have been inactive in posh within the timeframe and are ready to delete
    posh_users = (
        PoshUser.objects.filter(
            Q(is_active_in_posh=False) | Q(is_active=False),
            datetime_disabled__lt=timeframe,
        )
        .exclude(listeditem__status=ListedItem.REDEEMED_PENDING)
        .exclude(octo_uuid="")
    )
    octo_uuids = list(posh_users.values_list("octo_uuid", flat=True))

    octo_client = OctoAPIClient()

    chunk_size = 100
    for i in range(0, len(octo_uuids), chunk_size):
        chunk = octo_uuids[i : i + chunk_size]
        print(octo_client.delete_profiles(chunk))

    posh_users.update(octo_uuid="")

    try:
        redis_client = caches["default"].client.get_client()
        redis_client.delete(f"{profile_cleanup.name}")
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
