# Generated by Django 4.0.8 on 2022-12-23 17:32

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_alter_poshuser_date_of_birth_alter_poshuser_email_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="poshuser",
            name="username",
            field=models.CharField(blank=True, max_length=15, unique=True),
        ),
    ]
