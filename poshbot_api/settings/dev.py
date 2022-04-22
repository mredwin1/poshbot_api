from .common import *

DEBUG = True

SECRET_KEY = 'django-insecure-s(o=%hz@0mm%bt@wfi6&1tzj$q)gom4kfe$ll_#4i0%17hoaxt'

REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = ['rest_framework.renderers.BrowsableAPIRenderer']
