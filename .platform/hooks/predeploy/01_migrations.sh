#!/bin/bash

source /var/app/venv/*/bin/activate
cd /var/app/staging

mkdir -p /var/log/app-logs
chmod g+s /var/log/app-logs
setfacl -d -m g::rw /var/log/app-logs
chown wsgi:wsgi /var/log/app-logs

python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput