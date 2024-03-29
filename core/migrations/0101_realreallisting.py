# Generated by Django 5.0.1 on 2024-01-29 17:37

import core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0100_alter_proxy_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="RealRealListing",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("category", models.CharField(max_length=50)),
                ("brand", models.CharField(max_length=50)),
                ("item_type", models.CharField(max_length=50)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("NOT LISTED", "NOT LISTED"),
                            ("LISTED", "LISTED"),
                            ("SOLD", "SOLD"),
                            ("SHIPPED", "SHIPPED"),
                            ("CANCELLED", "CANCELLED"),
                        ],
                        default="NOT LISTED",
                        max_length=255,
                    ),
                ),
                ("datetime_listed", models.DateTimeField(blank=True, null=True)),
                (
                    "shipping_label",
                    models.FileField(upload_to=core.models.path_and_rename),
                ),
                (
                    "posh_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="real_real_listings",
                        to="core.poshuser",
                    ),
                ),
            ],
        ),
    ]
