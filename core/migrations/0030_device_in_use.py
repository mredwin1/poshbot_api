# Generated by Django 4.0.8 on 2023-02-05 23:05

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0029_device_delete_proxyconnection"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="in_use",
            field=models.BooleanField(default=False),
        ),
    ]
