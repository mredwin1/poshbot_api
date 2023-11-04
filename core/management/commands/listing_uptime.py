import logging
import datetime

from django.core.management.base import BaseCommand
from django.db.models import F, ExpressionWrapper, fields, Avg
from django.db.models.functions import Now, Coalesce

from core.models import ListedItem, User

class Command(BaseCommand):
    help = 'A command to return analytics'

    def add_arguments(self, parser):
        parser.add_argument(
            'start-date',
            type=str,
            help='Start date for filtering listed items (in the format YYYY-MM-DD)'
        )

        parser.add_argument(
            '--include-up',
            action='store_true',
            help='Include current items that are still UP'
        )

    @staticmethod
    def format_duration(duration):
        # Initialize the parts of the formatted duration
        days, seconds = duration.days, duration.seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        # Create a list to store the duration components
        components = []

        if days > 0:
            components.append(f"{days} {'day' if days == 1 else 'days'}")
        if hours > 0:
            components.append(f"{hours} {'hr' if hours == 1 else 'hrs'}")
        if minutes > 0:
            components.append(f"{minutes} {'min' if minutes == 1 else 'mins'}")
        if seconds > 0:
            components.append(f"{seconds} {'sec' if seconds == 1 else 'secs'}")

        # Join the components with spaces and return the formatted duration
        return ' '.join(components)

    def handle(self, *args, **options):
        logger = logging.getLogger(__name__)

        user_avg_durations = []
        excluded_statuses = (ListedItem.NOT_FOR_SALE, ListedItem.NOT_LISTED)
        time_to_be_removed_expression = ExpressionWrapper(
            Coalesce(F('datetime_removed'), Now()) - F('datetime_listed'),
            output_field=fields.DurationField()
        )

        users = User.objects.all()

        for user in users:
            listed_items = ListedItem.objects.filter(posh_user__user=user, datetime_listed__isnull=False).exclude(status__in=excluded_statuses)

            if options['include-up']:
                listed_items.exclude(datetime_listed__isnull=True)

            if options['start-date']:
                start_date_parts = options['start-date'].split()
                listed_items.filter(datetime_listed__gte=datetime.datetime(year=start_date_parts[0], month=start_date_parts[1], day=start_date_parts[2]))

            listed_items = listed_items.annotate(time_to_be_removed=time_to_be_removed_expression)

            average_duration = listed_items.aggregate(average_duration=Avg('time_to_be_removed'))['average_duration']

            user_avg_durations.append((user, average_duration))

        user_avg_durations.sort(key=lambda x: x[1])

        for user, average_duration in user_avg_durations:
            logger.info(f'The average time for {user} is: {self.format_duration(average_duration)}')