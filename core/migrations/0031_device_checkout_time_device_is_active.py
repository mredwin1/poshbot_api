# Generated by Django 4.0.8 on 2023-02-05 23:29

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0030_device_in_use"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="checkout_time",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="device",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
