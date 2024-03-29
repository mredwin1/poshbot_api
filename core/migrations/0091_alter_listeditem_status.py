# Generated by Django 4.0.10 on 2023-12-11 15:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0090_poshuser_cookies'),
    ]

    operations = [
        migrations.AlterField(
            model_name='listeditem',
            name='status',
            field=models.CharField(choices=[('NOT LISTED', 'NOT LISTED'), ('NOT FOR SALE', 'NOT FOR SALE'), ('UP', 'UP'), ('UNDER REVIEW', 'UNDER REVIEW'), ('RESERVED', 'RESERVED'), ('SOLD', 'SOLD'), ('REMOVED', 'REMOVED'), ('SHIPPED', 'SHIPPED'), ('CANCELLED', 'CANCELLED'), ('REDEEMABLE', 'REDEEMABLE'), ('REDEEMED', 'REDEEMED'), ('REDEEMED PENDING', 'REDEEMED PENDING')], default='NOT LISTED', max_length=255),
        ),
    ]
