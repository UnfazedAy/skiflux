from decimal import Decimal
from django.db import migrations


def seed_gateway_fees(apps, schema_editor):
    GatewayFeeConfig = apps.get_model("skiflux", "GatewayFeeConfig")

    fees_to_create = [
        # Flutterwave
        {
            "gateway_name": "flutterwave",
            "currency_code": "NGN",
            "fee_percentage": Decimal("1.40"),
            "cap_amount": Decimal("2000.00"),
        },
        {
            "gateway_name": "flutterwave",
            "currency_code": "USD",
            "fee_percentage": Decimal("3.95"),
            "vat_flat": Decimal("0.30"),
        },
        {
            "gateway_name": "flutterwave",
            "currency_code": "ALL",
            "fee_percentage": Decimal("3.80"),
        },
        # Paystack
        {
            "gateway_name": "paystack",
            "currency_code": "NGN",
            "fee_percentage": Decimal("1.50"),
            "flat_fee": Decimal("100.00"),
            "flat_fee_threshold": Decimal("2500.00"),
            "cap_amount": Decimal("2000.00"),
        },
        {
            "gateway_name": "paystack",
            "currency_code": "ALL",
            "fee_percentage": Decimal("3.90"),
        },
        # Stripe
        {
            "gateway_name": "stripe",
            "currency_code": "USD",
            "fee_percentage": Decimal("2.90"),
            "flat_fee": Decimal("0.30"),
        },
        {
            "gateway_name": "stripe",
            "currency_code": "ALL",
            "fee_percentage": Decimal("2.90"),
            "flat_fee": Decimal(
                "0.30"
            ),  # Handled via generic in base logic previously, but seeded here
        },
        # Adyen
        {
            "gateway_name": "adyen",
            "currency_code": "EUR",
            "fee_percentage": Decimal("0.30"),
            "flat_fee": Decimal("0.10"),
        },
        {
            "gateway_name": "adyen",
            "currency_code": "ALL",
            "fee_percentage": Decimal("0.30"),
            "flat_fee": Decimal("0.10"),
        },
    ]

    for data in fees_to_create:
        GatewayFeeConfig.objects.get_or_create(
            gateway_name=data["gateway_name"],
            currency_code=data["currency_code"],
            defaults={
                "fee_percentage": data.get("fee_percentage", Decimal("0.00")),
                "flat_fee": data.get("flat_fee", Decimal("0.00")),
                "flat_fee_threshold": data.get("flat_fee_threshold", Decimal("0.00")),
                "cap_amount": data.get("cap_amount"),
                "vat_percentage": data.get("vat_percentage", Decimal("0.00")),
                "vat_flat": data.get("vat_flat", Decimal("0.00")),
            },
        )


def reverse_seed_gateway_fees(apps, schema_editor):
    GatewayFeeConfig = apps.get_model("skiflux", "GatewayFeeConfig")
    GatewayFeeConfig.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("skiflux", "0076_add_gateway_fee_config"),
    ]

    operations = [migrations.RunPython(seed_gateway_fees, reverse_seed_gateway_fees)]
