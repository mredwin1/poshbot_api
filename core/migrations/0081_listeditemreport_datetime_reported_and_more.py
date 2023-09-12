# Generated by Django 4.0.8 on 2023-09-01 16:29

import datetime
from django.db import migrations, models
from django.utils.timezone import utc


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0080_alter_user_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='listeditemreport',
            name='datetime_reported',
            field=models.DateTimeField(auto_now_add=True, default=datetime.datetime(2023, 9, 1, 16, 29, 57, 991051, tzinfo=utc)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='listeditemtoreport',
            name='report_type',
            field=models.CharField(choices=[('Replica', 'Replica'), ('Mistagged Item', 'Mistagged Item'), ('Transaction Off Poshmark', 'Transaction Off Poshmark'), ('Unsupported Item', 'Unsupported Item'), ('Spam', 'Spam'), ('Harassment', 'Harassment')], default='Mistagged Item', max_length=100),
        ),
    ]