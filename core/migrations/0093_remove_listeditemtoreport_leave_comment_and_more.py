# Generated by Django 4.0.10 on 2023-12-15 04:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0092_remove_device_proxy_remove_poshuser_ads_id_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='listeditemtoreport',
            name='leave_comment',
        ),
        migrations.RemoveField(
            model_name='listeditemtoreport',
            name='send_bundle_message',
        ),
        migrations.RemoveField(
            model_name='poshuser',
            name='finished_registration',
        ),
        migrations.RemoveField(
            model_name='poshuser',
            name='time_to_finish_registration',
        ),
        migrations.AddField(
            model_name='proxy',
            name='proxy_uuid',
            field=models.CharField(default='test', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='proxy',
            name='vendor',
            field=models.CharField(default='replace', max_length=30),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='listing',
            name='listing_price',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name='listing',
            name='lowest_price',
            field=models.DecimalField(decimal_places=2, default=250, max_digits=10),
        ),
        migrations.AlterField(
            model_name='listing',
            name='original_price',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name='proxy',
            name='port',
            field=models.PositiveSmallIntegerField(),
        ),
        migrations.AlterField(
            model_name='proxy',
            name='type',
            field=models.CharField(choices=[('http', 'http'), ('socks', 'socks')], default='http', max_length=10),
        ),
    ]
