import logging
import os
import sys
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.utils import OperationalError

from core.models import User


class Command(BaseCommand):
    help = "An alternative to runserver which will run migrate and collectstatic beforehand"

    def handle(self, *args, **options):
        attempts_left = 5
        while attempts_left:
            try:
                logging.info("Trying to run migrations...")
                call_command("migrate")
                logging.info("Migrations complete")
                break
            except OperationalError as error:
                if error.args[0] == "FATAL:  the database system is starting up\n":
                    attempts_left -= 1
                    logging.warning(
                        "Cannot run migrations because the database system is starting up, retrying."
                    )
                    time.sleep(0.5)
                else:
                    sys.exit(f"Migrations unsuccessful. Error: {error.args}")
        else:
            logging.error("Migrations could not be run, exiting.")
            sys.exit("Migrations unsuccessful")

        super_username = "admin"
        if not User.objects.filter(username=super_username).exists():
            User.objects.create_superuser(
                username=super_username,
                password=os.environ["MASTER_USER_PASSWORD"],
            )
            logging.info("Superuser created.")
        else:
            logging.info("Superuser already created, skipping that step.")

        logging.info("Running collectstatic...")
        call_command("collectstatic", interactive=False, clear=True)

        logging.info("Starting server...")
        os.system(
            "gunicorn --preload -b 0.0.0.0:8000 poshbot_api.wsgi:application --threads 2 -w 2"
        )
        exit()
