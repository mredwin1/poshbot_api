# Generated by Django 4.0.8 on 2023-09-01 16:37

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0081_listeditemreport_datetime_reported_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="listeditemtoreport",
            name="leave_comment",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listeditemtoreport",
            name="send_bundle_message",
            field=models.BooleanField(default=False),
        ),
    ]
