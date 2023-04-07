import os

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from ppadb.client import Client as AdbClient

from core.models import PoshUser, Listing, ListingImage, LogEntry, ListedItem


@receiver(post_delete, sender=PoshUser)
def posh_user_deleted(sender, instance, *args, **kwargs):
    try:
        os.remove(f'/shared_volume/cookies/{instance.username}.pkl')
    except OSError:
        pass

    instance.profile_picture.delete(save=False)
    instance.header_picture.delete(save=False)

    if instance.app_package and instance.device:
        client = AdbClient(host=os.environ.get("LOCAL_SERVER_IP"), port=5037)
        device = client.device(instance.device.serial)

        device.uninstall(instance.app_package)

        if instance.device.installed_clones > 0:
            instance.device.installed_clones -= 1
            instance.device.save(update_fields=['installed_clones'])


@receiver(post_save, sender=PoshUser)
def posh_user_saved(sender, instance, *args, **kwargs):
    listed_items = ListedItem.objects.filter(posh_user=instance)

    if not instance.is_active_in_posh:
        for listed_item in listed_items:
            if listed_item.status not in (ListedItem.NOT_LISTED, ListedItem.SOLD, ListedItem.REMOVED):
                listed_item.datetime_removed = timezone.now()
                listed_item.status = ListedItem.REMOVED
                listed_item.save(update_fields=['status', 'datetime_removed'])


@receiver(post_delete, sender=Listing)
def listing_deleted(sender, instance, *args, **kwargs):
    instance.cover_photo.delete(save=False)


@receiver(post_delete, sender=ListingImage)
def listing_image_deleted(sender, instance, *args, **kwargs):
    instance.image.delete(save=False)


@receiver(post_delete, sender=LogEntry)
def log_entry_deleted(sender, instance, *args, **kwargs):
    instance.image.delete(save=False)
