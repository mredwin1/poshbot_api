# Generated by Django 4.0.4 on 2022-05-09 20:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_poshuser_is_active_alter_campaign_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campaign',
            name='mode',
            field=models.CharField(choices=[('0', 'Advanced Sharing'), ('0', 'Basic Sharing')], default='0', max_length=10),
        ),
    ]
