# Generated by Django 4.0.8 on 2023-04-15 16:47

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0061_poshuser_zipcode"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="poshuser",
            name="zipcode",
        ),
    ]
