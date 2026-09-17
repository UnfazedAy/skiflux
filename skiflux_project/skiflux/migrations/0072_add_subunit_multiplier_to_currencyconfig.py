from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0071_ticketattachment_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="currencyconfig",
            name="subunit_multiplier",
            field=models.PositiveIntegerField(
                default=100,
                help_text=(
                    "Smallest-unit multiplier for this currency. "
                    "Use 100 for 2-decimal currencies (USD, NGN, GBP, EUR, GHS, ZAR, KES). "
                    "Use 1000 for 3-decimal currencies (KWD, BHD). "
                    "Use 1 for 0-decimal currencies (JPY, KRW)."
                ),
            ),
        ),
    ]
