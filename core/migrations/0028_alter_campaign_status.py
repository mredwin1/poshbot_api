# Generated by Django 4.0.8 on 2023-02-04 22:41

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0027_campaign_next_runtime_alter_campaign_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="campaign",
            name="status",
            field=models.CharField(
                choices=[
                    ("RUNNING", "RUNNING"),
                    ("IDLE", "IDLE"),
                    ("STOPPED", "STOPPED"),
                    ("STARTING", "STARTING"),
                    ("STOPPING", "STOPPING"),
                    ("PAUSED", "PAUSED"),
                ],
                default="STOPPED",
                max_length=15,
            ),
        ),
    ]
