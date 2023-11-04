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
            '--include_up',
            type=bool,
            default=True,
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
        if options['include_up']:
            time_to_be_removed_expression = ExpressionWrapper(
                Coalesce(F('datetime_removed'), Now()) - F('datetime_listed'),
                output_field=fields.DurationField()
            )
        else:
            time_to_be_removed_expression = ExpressionWrapper(
                F('datetime_removed') - F('datetime_listed'),
                output_field=fields.DurationField()
            )

        users = User.objects.all()

        for user in users:
            listed_items = ListedItem.objects.filter(posh_user__user=user, datetime_listed__isnull=False, datetime_listed__gte=datetime.datetime(year=2023, day=1, month=11)).exclude(status__in=excluded_statuses)

            if not options['include_up']:
                listed_items.exclude(datetime_listed__isnull=True)

            listed_items = listed_items.annotate(time_to_be_removed=time_to_be_removed_expression)

            average_duration = listed_items.aggregate(average_duration=Avg('time_to_be_removed'))['average_duration']

            user_avg_durations.append((user, average_duration))

        user_avg_durations.sort(key=lambda x: x[1])

        for user, average_duration in user_avg_durations:
            logger.info(f'The average time for {user} is: {self.format_duration(average_duration)}')