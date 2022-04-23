import logging
import os
import socket
import sys
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.utils import OperationalError
from core.models import User, Campaign


class Command(BaseCommand):
    help = 'An alternative to runserver which will run migrate and collectstatic beforehand'

    def handle(self, *args, **options):
        superusername = os.environ.get('SUPER_USERNAME')
        if superusername:
            if not User.objects.filter(username=superusername).exists():
                User.objects.create_superuser(
                    username=superusername,
                    password=os.environ['SUPER_PASSWORD'],
                )
                logging.info('Superuser created.')
            else:
                logging.info('Superuser already created, skipping that step.')

        logging.info('Running collectstatic...')
        call_command("collectstatic", interactive=False, clear=True)

        logging.info('Setting all campaigns to IDLE status')
        campaigns = Campaign.objects.exclude(status=Campaign.IDLE)
        for campaign in campaigns:
            campaign.status = Campaign.IDLE
            campaign.save()

        logging.info('Starting server...')
        os.system("gunicorn --preload -b 0.0.0.0:80 poshbot_api.wsgi:application --threads 8 -w 4")
        exit()
