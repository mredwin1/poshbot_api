# Generated by Django 4.0.8 on 2022-12-30 16:42

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_alter_proxyconnection_proxy_license_uuid"),
    ]

    operations = [
        migrations.AddField(
            model_name="poshuser",
            name="email_id",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
