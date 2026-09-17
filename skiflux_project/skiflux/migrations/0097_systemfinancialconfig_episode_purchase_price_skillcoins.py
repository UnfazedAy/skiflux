from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0096_alter_systemfinancialconfig_card_verification_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemfinancialconfig",
            name="episode_purchase_price_skillcoins",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("25.00"),
                help_text="Skillcoin price charged when a learner purchases a paid episode.",
                max_digits=10,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
    ]
