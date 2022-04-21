from .common import *

DEBUG = True

SECRET_KEY = 'django-insecure-s(o=%hz@0mm%bt@wfi6&1tzj$q)gom4kfe$ll_#4i0%17hoaxt'

# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'poshbot',
        'USER': 'postgres',
        'PASSWORD': 'Apples2Apples!',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
