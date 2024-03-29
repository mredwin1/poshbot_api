# Generated by Django 5.0.1 on 2024-01-08 18:41

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0098_rename_proxy_uuid_proxy_change_ip_url_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="poshuser",
            name="date_added",
        ),
        migrations.RemoveField(
            model_name="poshuser",
            name="date_disabled",
        ),
        migrations.AddField(
            model_name="poshuser",
            name="datetime_added",
            field=models.DateTimeField(
                auto_now_add=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="poshuser",
            name="datetime_disabled",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
