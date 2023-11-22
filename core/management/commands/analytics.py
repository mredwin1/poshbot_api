import datetime
import logging

from django.core.management.base import BaseCommand
from django.db.models import Avg

from core.models import PoshUser, ListedItem


class Command(BaseCommand):
    help = "A command to return analytics"

    def handle(self, *args, **options):
        logger = logging.getLogger(__name__)

        posh_users = PoshUser.objects.exclude(
            time_to_install_clone=datetime.timedelta(seconds=0),
            time_to_register=datetime.timedelta(seconds=0),
            time_to_finish_registration=datetime.timedelta(seconds=0),
        )

        listed_items = ListedItem.objects.exclude(
            time_to_list=datetime.timedelta(seconds=0)
        )

        posh_user_averages = posh_users.aggregate(
            avg_time_to_install_clone=Avg("time_to_install_clone"),
            avg_time_to_register=Avg("time_to_register"),
            avg_time_to_finish_registration=Avg("time_to_finish_registration"),
        )

        listed_item_averages = listed_items.aggregate(
            avg_time_to_list=Avg("time_to_list")
        )

        logger.info(posh_user_averages)
        logger.info(listed_item_averages)
