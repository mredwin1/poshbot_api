from .common import *

DEBUG = True

CSRF_TRUSTED_ORIGINS = [
    'https://localhost'
]

CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
]

SECRET_KEY = 'django-insecure-s(o=%hz@0mm%bt@wfi6&1tzj$q)gom4kfe$ll_#4i0%17hoaxt'

REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'].append('rest_framework.renderers.BrowsableAPIRenderer')

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
