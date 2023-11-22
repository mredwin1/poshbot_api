from .common import *

DEBUG = False

ALLOWED_HOSTS = ["randomcol.com"]

CSRF_TRUSTED_ORIGINS = [
    "https://randomcol.com",
]

CORS_ALLOWED_ORIGINS = [
    "https://randomcol.com",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": os.environ["RDS_DB_NAME"],
        "USER": os.environ["RDS_USERNAME"],
        "PASSWORD": os.environ["RDS_PASSWORD"],
        "HOST": os.environ["RDS_HOSTNAME"],
        "PORT": os.environ["RDS_PORT"],
    }
}

DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

AWS_STORAGE_BUCKET_NAME = os.environ["AWS_STORAGE_BUCKET_NAME"]
AWS_S3_REGION_NAME = os.environ["AWS_S3_REGION_NAME"]

AWS_S3_ACCESS_KEY_ID = os.environ["AWS_S3_ACCESS_KEY_ID"]
AWS_S3_SECRET_ACCESS_KEY = os.environ["AWS_S3_SECRET_ACCESS_KEY"]

# Pinpoint settings
AWS_PINPOINT_REGION_NAME = os.environ["AWS_PINPOINT_REGION_NAME"]
AWS_PINPOINT_ACCESS_KEY_ID = os.environ["AWS_PINPOINT_ACCESS_KEY_ID"]
AWS_PINPOINT_SECRET_ACCESS_KEY = os.environ["AWS_PINPOINT_SECRET_ACCESS_KEY"]

CELERY_DEFAULT_QUEUE = "maintenance"
CELERY_BROKER_URL = f"sqs://{os.environ.get('AWS_SQS_ACCESS_KEY_ID')}:{os.environ.get('AWS_SQS_SECRET_ACCESS_KEY')}@"
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "region": "",
    "visibility_timeout": 7200,
    "polling_interval": 1,
}

CELERY_TASK_ROUTES = {
    "core.tasks.CampaignTask": {
        "queue": "campaign_concurrency",
        "routing_key": "campaign_concurrency",
    },
    "core.tasks.ManageCampaignsTask": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "core.tasks.CheckPoshUsers": {"queue": "maintenance", "routing_key": "maintenance"},
    "core.tasks.send_email": {"queue": "maintenance", "routing_key": "maintenance"},
    "core.tasks.check_posh_users": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "core.tasks.send_support_emails": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "core.tasks.log_cleanup": {"queue": "maintenance", "routing_key": "maintenance"},
    "imagekit.cachefiles.backends._generate_file": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "core.tasks.posh_user_cleanup": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "celery.backend_cleanup": {"queue": "maintenance", "routing_key": "maintenance"},
    "core.tasks.get_items_to_report": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "core.tasks.check_sold_items": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "core.tasks.test_task": {"queue": "maintenance", "routing_key": "maintenance"},
}

CELERY_BEAT_SCHEDULE = {
    "manage_campaigns": {
        "task": "core.tasks.ManageCampaignsTask",
        "schedule": timedelta(seconds=30),
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
    "check_sold_items": {
        "task": "core.tasks.check_sold_items",
        "schedule": timedelta(minutes=5),
    },
}
