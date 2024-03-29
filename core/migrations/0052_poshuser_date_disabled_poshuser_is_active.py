# Generated by Django 4.0.8 on 2023-03-31 14:34

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0051_rename_is_active_poshuser_is_active_in_posh"),
    ]

    operations = [
        migrations.AddField(
            model_name="poshuser",
            name="date_disabled",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="poshuser",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
