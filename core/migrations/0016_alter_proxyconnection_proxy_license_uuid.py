# Generated by Django 4.0.8 on 2022-12-29 02:47

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_alter_proxyconnection_proxy_license_uuid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="proxyconnection",
            name="proxy_license_uuid",
            field=models.UUIDField(),
        ),
    ]
