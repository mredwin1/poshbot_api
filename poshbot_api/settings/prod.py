import socket
from .common import *

DEBUG = False

SECRET_KEY = os.environ.get('SECRET_KEY')

hostname = socket.gethostname()
local_ip = socket.gethostbyname(hostname)

ALLOWED_HOSTS = [
    'api.poshbot.net',
    local_ip
]

CORS_ALLOWED_ORIGINS = [
    'http://api.poshbot.net/'
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

STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

AWS_STORAGE_BUCKET_NAME = os.environ['AWS_STORAGE_BUCKET_NAME']
AWS_S3_REGION_NAME = os.environ['AWS_S3_REGION_NAME']

AWS_S3_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']
AWS_S3_SECRET_ACCESS_KEY = os.environ['AWS_SECRET_ACCESS_KEY']

del socket
