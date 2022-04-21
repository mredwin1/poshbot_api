import os
from .common import *

DEBUG = False

SECRET_KEY = os.environ.get('SECRET_KEY')

ALLOWED_HOSTS = [
    'http://poshbot-api-prod.us-east-1.elasticbeanstalk.com/'
]
