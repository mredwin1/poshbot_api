import os

from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.models import PoshUser


@receiver(post_delete, sender=PoshUser)
def posh_user_deleted(sender, instance, *args, **kwargs):
    try:
        instance.delete_email()
    except:
        pass

    try:
        os.remove(f'/shared_volume/cookies/{instance.username}.pkl')
    except OSError:
        pass
