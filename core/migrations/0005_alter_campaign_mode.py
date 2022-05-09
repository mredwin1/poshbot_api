# Generated by Django 4.0.4 on 2022-05-09 20:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_alter_campaign_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campaign',
            name='mode',
            field=models.CharField(choices=[('0', 'Advanced Sharing'), ('1', 'Basic Sharing')], default='0', max_length=10),
        ),
    ]
