# Generated by Django 4.0.8 on 2023-01-02 23:37

import uuid

import django.db.models.deletion
import imagekit.models.fields
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_alter_proxyconnection_proxy_license_uuid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="poshuser",
            name="header_picture",
            field=models.ImageField(
                blank=True, null=True, upload_to=core.models.path_and_rename
            ),
        ),
        migrations.AlterField(
            model_name="poshuser",
            name="profile_picture",
            field=models.ImageField(
                blank=True, null=True, upload_to=core.models.path_and_rename
            ),
        ),
        migrations.CreateModel(
            name="LogGroup",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_date", models.DateTimeField(editable=False)),
                (
                    "campaign",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="core.campaign"
                    ),
                ),
                (
                    "posh_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="core.poshuser"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="LogEntry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("level", models.IntegerField()),
                ("timestamp", models.DateTimeField()),
                ("message", models.TextField()),
                (
                    "image",
                    imagekit.models.fields.ProcessedImageField(
                        upload_to=core.models.path_and_rename
                    ),
                ),
                (
                    "log_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="core.loggroup"
                    ),
                ),
            ],
        ),
    ]
