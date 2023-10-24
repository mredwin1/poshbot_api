from .common import *

DEBUG = False

SECRET_KEY = os.environ.get('SECRET_KEY')

ALLOWED_HOSTS = [
    'turtleswags.com'
]

CSRF_TRUSTED_ORIGINS = [
    'https://melondova.com',
    'https://turtleswags.com',
    'https://www.melondova.com'
]

CORS_ALLOWED_ORIGINS = [
    'https://turtleswags.com',
    'https://www.turtleswags.com',
    'https://melondova.com',
    'https://www.melondova.com'
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': os.environ['RDS_DB_NAME'],
        'USER': os.environ['RDS_USERNAME'],
        'PASSWORD': os.environ['RDS_PASSWORD'],
        'HOST': os.environ['RDS_HOSTNAME'],
        'PORT': os.environ['RDS_PORT'],
    }
}

DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

AWS_STORAGE_BUCKET_NAME = os.environ['AWS_STORAGE_BUCKET_NAME']
AWS_S3_REGION_NAME = os.environ['AWS_S3_REGION_NAME']

AWS_S3_ACCESS_KEY_ID = os.environ['AWS_S3_ACCESS_KEY_ID']
AWS_S3_SECRET_ACCESS_KEY = os.environ['AWS_S3_SECRET_ACCESS_KEY']

# Pinpoint settings
AWS_PINPOINT_REGION_NAME = os.environ['AWS_PINPOINT_REGION_NAME']
AWS_PINPOINT_ACCESS_KEY_ID = os.environ['AWS_PINPOINT_ACCESS_KEY_ID']
AWS_PINPOINT_SECRET_ACCESS_KEY = os.environ['AWS_PINPOINT_SECRET_ACCESS_KEY']

