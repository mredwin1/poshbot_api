# Generated by Django 4.0.8 on 2023-04-22 15:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0064_poshuser_email_imap_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='listeditem',
            name='listed_item_id',
            field=models.CharField(default=None, max_length=255),
            preserve_default=False,
        ),
    ]
