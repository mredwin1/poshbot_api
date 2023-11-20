import logging

from django.core.management.base import BaseCommand

from core.models import PoshUser, User


class Command(BaseCommand):
    help = "A command to return analytics"

    def handle(self, *args, **options):
        logger = logging.getLogger(__name__)

        users = User.objects.all()

        for user in users:
            posh_users = PoshUser.objects.filter(is_registered=True, user=user)

            active_posh_users = posh_users.filter(is_active_in_posh=True)
            inactive_posh_users = posh_users.filter(is_active_in_posh=False)

            logger.info(f"Number of Registered Posh Users for {user}")
            logger.info(f"Active: {active_posh_users.count()}")
            logger.info(f"Inactive: {inactive_posh_users.count()}\n")
