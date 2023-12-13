from .common import *

ALLOWED_HOSTS = [f"{os.environ['DOMAIN'].replace('api.', '')}", os.environ["DOMAIN"]]

CSRF_TRUSTED_ORIGINS = [
    f"https://{os.environ['DOMAIN'].replace('api.', '')}",
    f"https://{os.environ['DOMAIN']}",
]

CORS_ALLOWED_ORIGINS = [
    f"https://{os.environ['DOMAIN'].replace('api.', '')}",
    f"https://{os.environ['DOMAIN']}",
]

DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

AWS_STORAGE_BUCKET_NAME = os.environ["AWS_STORAGE_BUCKET_NAME"]

CELERY_CREATE_MISSING_QUEUES = False
CELERY_DEFAULT_QUEUE = os.environ["MAINTENANCE_QUEUE"]
CELERY_BROKER_URL = f"sqs://"
CELERY_BROKER_CONNECTION_RETRY_ON_START_UP = True

CELERY_TASK_ROUTES = {
    "core.tasks.CampaignTask": {
        "queue": os.environ["GENERAL_QUEUE"],
        "routing_key": os.environ["GENERAL_QUEUE"],
    },
    "core.tasks.ManageCampaignsTask": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.CheckPoshUsers": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.send_email": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.check_posh_users": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.send_support_emails": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.log_cleanup": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "imagekit.cachefiles.backends._generate_file": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.posh_user_cleanup": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "celery.backend_cleanup": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.get_items_to_report": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
    "core.tasks.check_listed_items": {
        "queue": os.environ["MAINTENANCE_QUEUE"],
        "routing_key": os.environ["MAINTENANCE_QUEUE"],
    },
}

CELERY_BEAT_SCHEDULE = {
    "manage_campaigns": {
        "task": "core.tasks.ManageCampaignsTask",
        "schedule": timedelta(seconds=10),
    },
    "check_posh_users": {
        "task": "core.tasks.CheckPoshUsers",
        "schedule": timedelta(minutes=20),
    },
    "log_cleanup": {
        "task": "core.tasks.log_cleanup",
        "schedule": timedelta(hours=1),
    },
    "posh_user_cleanup": {
        "task": "core.tasks.posh_user_cleanup",
        "schedule": timedelta(hours=4),
    },
    "send_support_emails": {
        "task": "core.tasks.send_support_emails",
        "schedule": timedelta(days=4),
    },
    "check_listed_items": {
        "task": "core.tasks.check_listed_items",
        "schedule": timedelta(minutes=5),
    },
}
