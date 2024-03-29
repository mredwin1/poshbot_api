# Generated by Django 4.0.8 on 2023-08-31 00:45

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0075_alter_badphrase_report_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="listeditem",
            name="status",
            field=models.CharField(
                choices=[
                    ("NOT LISTED", "NOT LISTED"),
                    ("NOT FOR SALE", "NOT FOR SALE"),
                    ("UP", "UP"),
                    ("UNDER REVIEW", "UNDER REVIEW"),
                    ("RESERVED", "RESERVED"),
                    ("SOLD", "SOLD"),
                    ("REMOVED", "REMOVED"),
                    ("SHIPPED", "SHIPPED"),
                    ("CANCELLED", "CANCELLED"),
                    ("REDEEMABLE", "REDEEMABLE"),
                ],
                default="NOT LISTED",
                max_length=255,
            ),
        ),
    ]
