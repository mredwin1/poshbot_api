# Generated by Django 4.0.8 on 2023-02-19 04:12

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0036_listeditem'),
    ]

    operations = [
        migrations.AddField(
            model_name='listeditem',
            name='listing_title',
            field=models.CharField(default='Not here', max_length=50),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='listeditem',
            name='listing',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.listing'),
        ),
    ]
