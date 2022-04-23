#!/bin/bash

mkdir /var/log/app_logs
chmod g+s /var/log/app_logs
setfacl -d -m g::rw /var/log/app_logs
chown wsgi:wsgi /var/log/app_logs