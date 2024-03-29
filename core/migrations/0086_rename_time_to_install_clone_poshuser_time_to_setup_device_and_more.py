# Generated by Django 4.0.8 on 2023-09-21 20:09

import uuid

import django.db.models.deletion
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0085_proxy_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="poshuser",
            old_name="time_to_install_clone",
            new_name="time_to_setup_device",
        ),
        migrations.RemoveField(
            model_name="device",
            name="installed_clones",
        ),
        migrations.RemoveField(
            model_name="poshuser",
            name="app_package",
        ),
        migrations.RemoveField(
            model_name="poshuser",
            name="clone_installed",
        ),
        migrations.RemoveField(
            model_name="poshuser",
            name="device",
        ),
        migrations.AddField(
            model_name="poshuser",
            name="ads_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="android_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="bluetooth_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="gsf",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="hw_serial",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="imei1",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="imei2",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="media_drm",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="mobile_number",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="sim_serial",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="sim_sub_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="wifi_bssid",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="wifi_mac",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="wifi_ssid",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.CreateModel(
            name="AppData",
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
                (
                    "backup_data",
                    models.FileField(upload_to=core.models.path_and_rename),
                ),
                ("xml_data", models.FileField(upload_to=core.models.path_and_rename)),
                (
                    "type",
                    models.CharField(
                        choices=[("POSHMARK", "POSHMARK")],
                        default="POSHMARK",
                        max_length=10,
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
    ]
