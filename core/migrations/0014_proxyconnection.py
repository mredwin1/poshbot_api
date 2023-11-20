# Generated by Django 4.0.8 on 2022-12-29 01:58

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_campaign_lowest_price"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProxyConnection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_date", models.DateTimeField()),
                ("in_use", models.BooleanField(default=True)),
                ("proxy_license_uuid", models.UUIDField()),
                ("proxy_name", models.CharField(max_length=255)),
                (
                    "campaign",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="core.campaign",
                    ),
                ),
            ],
        ),
    ]
