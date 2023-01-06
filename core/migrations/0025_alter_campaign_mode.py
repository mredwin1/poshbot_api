# Generated by Django 4.0.8 on 2023-01-06 17:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_alter_campaign_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campaign',
            name='mode',
            field=models.CharField(choices=[('0', 'Advanced Sharing'), ('1', 'Basic Sharing'), ('2', 'Bot Tests')], default='0', max_length=10),
        ),
    ]