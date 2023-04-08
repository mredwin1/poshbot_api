"""
Django settings for poshbot_api project.

Generated by 'django-admin startproject' using Django 4.0.3.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""
import os

from datetime import timedelta
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.sessions',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'debug_toolbar',
    'django_filters',
    'storages',
    'djoser',
    'corsheaders',
    'core'
]

INTERNAL_IPS = [
    "127.0.0.1",
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'poshbot_api.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'poshbot_api.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'core.User'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 1000
}

SIMPLE_JWT = {
    'AUTH_HEADER_TYPES': ('JWT',),
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1)
}

DJOSER = {
    'SERIALIZERS': {
        'user_create': 'core.serializers.UserCreateSerializer',
        'current_user': 'core.serializers.UserCreateSerializer',
    }
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        # 'file': {
        #     'class': 'logging.FileHandler',
        #     'filename': '/var/log/app_logs/general.log',
        #     'formatter': 'verbose'
        # },
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
        }
    },
    'formatters': {
        'verbose': {
            'format': '{asctime} ({levelname}) - {name} - {message}',
            'style': '{'
        }
    }
}

CELERY_RESULT_BACKEND = None
CELERY_IGNORE_RESULT = True
CELERY_DEFAULT_QUEUE = 'maintenance'
CELERY_BROKER_URL = f"sqs://{os.environ.get('AWS_SQS_ACCESS_KEY_ID')}:{os.environ.get('AWS_SQS_SECRET_ACCESS_KEY')}@"
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'region': '',
    'visibility_timeout': 7200,
    'polling_interval': 1
}

CELERY_TASK_ROUTES = {
    'core.tasks.CampaignTask': {'queue': 'campaign_concurrency', 'routing_key': 'campaign_concurrency'},
    'core.tasks.KillCampaignTask': {'queue': 'campaign_concurrency', 'routing_key': 'campaign_concurrency'},
    'core.tasks.start_campaigns': {'queue': 'maintenance', 'routing_key': 'maintenance'},
    'core.tasks.check_posh_users': {'queue': 'maintenance', 'routing_key': 'maintenance'},
    'core.tasks.log_cleanup': {'queue': 'maintenance', 'routing_key': 'maintenance'},
    'imagekit.cachefiles.backends._generate_file': {'queue': 'maintenance', 'routing_key': 'maintenance'},
    'core.tasks.posh_user_cleanup': {'queue': 'maintenance', 'routing_key': 'maintenance'},
    'celery.backend_cleanup': {'queue': 'maintenance', 'routing_key': 'maintenance'},
}

CELERY_BEAT_SCHEDULE = {
    'start_campaigns': {
        'task': 'core.tasks.start_campaigns',
        'schedule': timedelta(seconds=10),
        'options': {'scheduler_cls': 'core.tasks.DedupScheduler'}
    },
    'check_posh_users': {
        'task': 'core.tasks.check_posh_users',
        'schedule': timedelta(minutes=10),
        'options': {'scheduler_cls': 'core.tasks.DedupScheduler'}
    },
    'log_cleanup': {
        'task': 'core.tasks.log_cleanup',
        'schedule': timedelta(hours=1),
        'options': {'scheduler_cls': 'core.tasks.DedupScheduler'}
    },
    'posh_user_cleanup': {
        'task': 'core.tasks.posh_user_cleanup',
        'schedule': timedelta(days=1),
        'options': {'scheduler_cls': 'core.tasks.DedupScheduler'}
    },
}