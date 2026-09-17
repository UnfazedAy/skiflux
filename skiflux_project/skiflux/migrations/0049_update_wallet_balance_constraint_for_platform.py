from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0048_skillcointransaction_parent_transaction"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="userwallet",
            name="wallet_balance_cannot_be_negative",
        ),
        migrations.AddConstraint(
            model_name="userwallet",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("balance__gte", Decimal("0.00")))
                    | models.Q(("is_platform_wallet", True))
                ),
                name="wallet_balance_cannot_be_negative",
            ),
        ),
    ]
