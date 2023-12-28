# Generated by Django 5.0 on 2023-12-28 01:40

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0095_alter_listing_listing_price_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="badphrase",
            name="report_type",
            field=models.CharField(
                choices=[
                    ("Transaction Off Poshmark", "Transaction Off Poshmark"),
                    ("Offensive Comment", "Offensive Comment"),
                    ("Spam", "Spam"),
                    ("Harassment", "Harassment"),
                ],
                default="Spam",
                max_length=255,
            ),
        ),
    ]
