import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'poshbot_api.settings.dev')

app = Celery('poshbot_api')
app.config_from_object('django.conf:settings', namespace='CELERY')
# app.conf.beat_scheduler = 'core.tasks.DedupScheduler'
app.autodiscover_tasks()
