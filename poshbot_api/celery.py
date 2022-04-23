import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'poshbot_api.settings.dev')

celery = Celery('poshbot_api')
celery.config_from_object('django.conf:settings', namespace='CELERY')
celery.autodiscover_tasks()
