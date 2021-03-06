import logging
import os
import sys
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.utils import OperationalError
from core.models import User, Campaign


class Command(BaseCommand):
    help = 'An alternative to runserver which will run migrate and collectstatic beforehand'

    def handle(self, *args, **options):
        attempts_left = 5
        while attempts_left:
            try:
                logging.info('Trying to run migrations...')
                call_command("migrate")
                logging.info('Migrations complete')
                break
            except OperationalError as error:
                if error.args[0] == 'FATAL:  the database system is starting up\n':
                    attempts_left -= 1
                    logging.warning('Cannot run migrations because the database system is starting up, retrying.')
                    time.sleep(0.5)
                else:
                    sys.exit(f'Migrations unsuccessful. Error: {error.args}')
        else:
            logging.error('Migrations could not be run, exiting.')
            sys.exit('Migrations unsuccessful')

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
        campaigns = Campaign.objects.exclude(status=Campaign.STOPPED)
        for campaign in campaigns:
            campaign.status = Campaign.STOPPED
            campaign.save()

        logging.info('Starting server...')
        os.system("gunicorn --preload -b 0.0.0.0:80 poshbot_api.wsgi:application --threads 8 -w 4")
        exit()
