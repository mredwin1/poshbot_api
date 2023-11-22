# Generated by Django 4.0.8 on 2023-09-12 19:18

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0084_remove_device_ip_reset_url_device_proxy"),
    ]

    operations = [
        migrations.AddField(
            model_name="proxy",
            name="type",
            field=models.CharField(
                choices=[("http", "http"), ("socks5", "socks5")],
                default="http",
                max_length=10,
            ),
        ),
    ]
