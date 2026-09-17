from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from skiflux.gateways.flutterwave import FlutterwaveGateway
from skiflux.models import User
from skiflux.models.currency import CurrencyConfig
from skiflux.models.wallet import (
    GatewayFeeConfig,
    PaymentTransaction,
    SystemFinancialConfig,
)
from skiflux.services.payment_service import PaymentService


@pytest.mark.django_db
class TestGatewayFeeConfigCalculator:
    def setup_method(self):
        self.gw = FlutterwaveGateway()

    def test_fee_is_zero_when_no_config(self):
        GatewayFeeConfig.objects.all().delete()
        fee = self.gw.calculate_fee(Decimal("1000.00"), "NGN")
        assert fee == Decimal("0.00")

    def test_percentage_fee_only(self):
        GatewayFeeConfig.objects.update_or_create(
            gateway_name="flutterwave",
            currency_code="NGN",
            defaults={"fee_percentage": Decimal("1.40")},
        )
        fee = self.gw.calculate_fee(Decimal("1000.00"), "NGN")
        assert fee == Decimal("14.00")

    def test_percentage_and_flat_fee(self):
        GatewayFeeConfig.objects.update_or_create(
            gateway_name="flutterwave",
            currency_code="USD",
            defaults={
                "fee_percentage": Decimal("2.90"),
                "flat_fee": Decimal("0.30"),
                "vat_flat": Decimal("0.00"),
                "vat_percentage": Decimal("0.00"),
            },
        )
        fee = self.gw.calculate_fee(Decimal("100.00"), "USD")
        assert fee == Decimal("3.20")

    def test_flat_fee_threshold(self):
        GatewayFeeConfig.objects.update_or_create(
            gateway_name="flutterwave",
            currency_code="NGN",
            defaults={
                "fee_percentage": Decimal("1.50"),
                "flat_fee": Decimal("100.00"),
                "flat_fee_threshold": Decimal("2500.00"),
            },
        )
        fee_low = self.gw.calculate_fee(Decimal("1000.00"), "NGN")
        assert fee_low == Decimal("15.00")

        fee_high = self.gw.calculate_fee(Decimal("3000.00"), "NGN")
        assert fee_high == Decimal("145.00")

    def test_fee_cap(self):
        GatewayFeeConfig.objects.update_or_create(
            gateway_name="flutterwave",
            currency_code="NGN",
            defaults={
                "fee_percentage": Decimal("1.40"),
                "cap_amount": Decimal("2000.00"),
            },
        )
        fee = self.gw.calculate_fee(Decimal("500000.00"), "NGN")
        assert fee == Decimal("2000.00")

    def test_vat_percentage_and_flat(self):
        GatewayFeeConfig.objects.update_or_create(
            gateway_name="flutterwave",
            currency_code="NGN",
            defaults={
                "fee_percentage": Decimal("1.50"),
                "vat_percentage": Decimal("7.50"),
                "vat_flat": Decimal("0.30"),
            },
        )
        fee = self.gw.calculate_fee(Decimal("1000.00"), "NGN")
        # Base fee = 1000 * 1.5% = 15.00
        # VAT % = 15.00 * 7.5% = 1.125 (rounds down to 1.12 due to ROUND_HALF_EVEN)
        # VAT Flat = 0.30
        # Total = 15.00 + 1.12 + 0.30 = 16.42
        assert fee == Decimal("16.42")

    def test_fallback_to_all_currency(self):
        GatewayFeeConfig.objects.update_or_create(
            gateway_name="flutterwave",
            currency_code="ALL",
            defaults={"fee_percentage": Decimal("3.80")},
        )
        fee = self.gw.calculate_fee(Decimal("100.00"), "GBP")
        assert fee == Decimal("3.80")


@pytest.fixture
def payment_service():
    return PaymentService()


@pytest.fixture
def test_user(db):
    return User.objects.create(email="fee_test@test.com", password="pwd")


@pytest.mark.django_db
class TestFeePassThrough:
    def _setup_config(self, pass_fees: bool = True):
        config = SystemFinancialConfig.get_config()
        config.default_currency = "NGN"
        config.enabled_topup_gateways = ["flutterwave"]
        config.pass_gateway_fees_to_customer = pass_fees
        config.save()

        CurrencyConfig.objects.get_or_create(
            currency_code="NGN",
            defaults={
                "currency_name": "Naira",
                "currency_symbol": "₦",
                "skillcoin_rate": Decimal("5.00"),
                "is_active": True,
                "supported_gateways": ["flutterwave"],
            },
        )

        GatewayFeeConfig.objects.get_or_create(
            gateway_name="flutterwave",
            currency_code="NGN",
            defaults={
                "fee_percentage": Decimal("1.40"),
            },
        )

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.initiate_payment")
    def test_fee_added_when_enabled(
        self,
        mock_initiate,
        payment_service,
        test_user,
    ):
        self._setup_config(pass_fees=True)
        mock_initiate.return_value = MagicMock(
            checkout_url="https://flw.com/pay/1", gateway_reference="ref-1"
        )

        result = payment_service.initiate_topup(
            user=test_user,
            amount_fiat=Decimal("1000.00"),
            gateway_name="flutterwave",
        )
        assert result["gateway_fee"] == "14.00"
        assert result["charged_amount"] == "1014.00"
        assert result["amount_fiat"] == "1000.00"
        call_kwargs = mock_initiate.call_args
        assert call_kwargs.kwargs["amount"] == Decimal("1014.00")
        tx = PaymentTransaction.objects.get(id=result["transaction_id"])
        assert tx.amount_fiat == Decimal("1000.00")
        assert tx.amount_skillcoins == Decimal("200.00")

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.initiate_payment")
    def test_no_fee_when_disabled(
        self,
        mock_initiate,
        payment_service,
        test_user,
    ):
        self._setup_config(pass_fees=False)
        mock_initiate.return_value = MagicMock(
            checkout_url="https://flw.com/pay/2", gateway_reference="ref-2"
        )

        result = payment_service.initiate_topup(
            user=test_user,
            amount_fiat=Decimal("1000.00"),
            gateway_name="flutterwave",
        )

        assert result["gateway_fee"] == "0.00"
        assert result["charged_amount"] == "1000.00"
        assert result["amount_fiat"] == "1000.00"
        call_kwargs = mock_initiate.call_args
        assert call_kwargs.kwargs["amount"] == Decimal("1000.00")

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.initiate_payment")
    def test_existing_test_still_passes(
        self, mock_initiate, payment_service, test_user
    ):
        self._setup_config(pass_fees=True)

        mock_initiate.return_value = MagicMock(
            checkout_url="https://flw.com/pay/123",
            gateway_reference="flw-ref-123",
        )
        result = payment_service.initiate_topup(
            user=test_user,
            amount_fiat=Decimal("1000.00"),
            gateway_name="flutterwave",
        )
        assert "transaction_id" in result
        assert result["checkout_url"] == "https://flw.com/pay/123"
        tx = PaymentTransaction.objects.get(id=result["transaction_id"])
        assert tx.amount_fiat == Decimal("1000.00")
        assert tx.amount_skillcoins == Decimal("200.00")
        assert tx.status == PaymentTransaction.Status.PENDING
        assert tx.gateway_reference == "flw-ref-123"
