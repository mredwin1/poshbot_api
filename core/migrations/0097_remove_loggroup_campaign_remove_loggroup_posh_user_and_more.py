# Generated by Django 5.0 on 2023-12-28 01:43

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0096_alter_badphrase_report_type"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="loggroup",
            name="campaign",
        ),
        migrations.RemoveField(
            model_name="loggroup",
            name="posh_user",
        ),
        migrations.DeleteModel(
            name="LogEntry",
        ),
        migrations.DeleteModel(
            name="LogGroup",
        ),
    ]
