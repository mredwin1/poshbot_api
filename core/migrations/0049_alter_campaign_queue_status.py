# Generated by Django 4.0.8 on 2023-03-18 18:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_alter_device_in_use'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campaign',
            name='queue_status',
            field=models.CharField(default='N/A', max_length=15),
        ),
    ]
