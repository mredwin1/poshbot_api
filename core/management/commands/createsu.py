import logging
import os

from django.core.management.base import BaseCommand
from core.models import User


class Command(BaseCommand):
    help = 'Creates a super user'

    def handle(self, *args, **options):
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                username='admin',
                password='SadPassword',
            )
            logging.info('Superuser created.')
        else:
            logging.info('Superuser already created, skipping that step.')
