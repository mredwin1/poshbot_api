# Generated by Django 4.0.8 on 2023-01-03 00:05

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_alter_poshuser_header_picture_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='loggroup',
            name='campaign',
        ),
        migrations.RemoveField(
            model_name='loggroup',
            name='posh_user',
        ),
        migrations.DeleteModel(
            name='LogEntry',
        ),
        migrations.DeleteModel(
            name='LogGroup',
        ),
    ]