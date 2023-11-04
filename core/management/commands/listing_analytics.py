import logging

from django.core.management.base import BaseCommand
from django.db.models import F, ExpressionWrapper, fields, Avg

from core.models import ListedItem, User

class Command(BaseCommand):
    help = 'A command to return analytics'

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

        excluded_statuses = (ListedItem.NOT_FOR_SALE, ListedItem.NOT_LISTED)
        time_to_be_removed_expression = ExpressionWrapper(
            F('datetime_removed') - F('datetime_listed'),
            output_field=fields.DurationField()
        )

        users = User.objects.all()

        for user in users:
            listed_items = ListedItem.objects.filter(posh_user__user=user).exclude(status__in=excluded_statuses)
            listed_items = listed_items.annotate(time_to_be_removed=time_to_be_removed_expression)

            average_duration = listed_items.aggregate(average_duration=Avg('duration'))['average_duration']

            logger.info(f'The average time for {user} is: {self.format_duration(average_duration)}')