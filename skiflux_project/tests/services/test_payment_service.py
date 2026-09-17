from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.exceptions import ValidationError

from skiflux.models import User
from skiflux.models.wallet import PaymentTransaction, SystemFinancialConfig
from skiflux.models.currency import CurrencyConfig
from skiflux.services.payment_service import PaymentService


@pytest.fixture
def payment_service():
    return PaymentService()


@pytest.fixture
def test_user(db):
    return User.objects.create(email="user@test.com", password="pwd")


@pytest.mark.django_db
class TestPaymentService:
    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.initiate_payment")
    def test_initiate_topup(self, mock_initiate, payment_service, test_user):
        config = SystemFinancialConfig.get_config()
        config.default_currency = "NGN"
        config.enabled_topup_gateways = ["flutterwave"]
        config.save()

        CurrencyConfig.objects.create(
            currency_code="NGN",
            skillcoin_rate=Decimal("5.00"),
            is_active=True,
            supported_gateways=["flutterwave"],
        )

        mock_initiate.return_value = MagicMock(
            checkout_url="https://flw.com/pay/123", gateway_reference="flw-ref-123"
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

    @patch("skiflux.gateways.paystack.PaystackGateway.initiate_payment")
    def test_initiate_topup_passes_payment_method(
        self, mock_initiate, payment_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.default_currency = "NGN"
        config.enabled_topup_gateways = ["paystack"]
        config.save()

        CurrencyConfig.objects.create(
            currency_code="NGN",
            skillcoin_rate=Decimal("1.00"),
            is_active=True,
            supported_gateways=["paystack"],
        )

        mock_initiate.return_value = MagicMock(
            checkout_url="https://paystack.com/pay/123",
            gateway_reference="ps-ref-123",
        )

        payment_service.initiate_topup(
            user=test_user,
            amount_fiat=Decimal("1000.00"),
            gateway_name="paystack",
            payment_method="bank_transfer",
        )

        assert mock_initiate.call_args.kwargs["payment_method"] == "bank_transfer"

    def test_initiate_topup_rejects_save_card_with_bank_transfer(
        self, payment_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.default_currency = "NGN"
        config.enabled_topup_gateways = ["paystack"]
        config.save()

        CurrencyConfig.objects.create(
            currency_code="NGN",
            skillcoin_rate=Decimal("1.00"),
            is_active=True,
            supported_gateways=["paystack"],
        )

        with pytest.raises(ValidationError, match="save_card is only supported"):
            payment_service.initiate_topup(
                user=test_user,
                amount_fiat=Decimal("1000.00"),
                gateway_name="paystack",
                save_card=True,
                payment_method="bank_transfer",
            )

    def test_initiate_topup_rejects_bank_transfer_on_stripe(
        self, payment_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.default_currency = "USD"
        config.enabled_topup_gateways = ["stripe"]
        config.save()

        CurrencyConfig.objects.create(
            currency_code="USD",
            skillcoin_rate=Decimal("0.10"),
            is_active=True,
            supported_gateways=["stripe"],
        )

        with pytest.raises(ValidationError, match="Bank transfer is not supported"):
            payment_service.initiate_topup(
                user=test_user,
                amount_fiat=Decimal("100.00"),
                gateway_name="stripe",
                payment_method="bank_transfer",
            )

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.verify_payment")
    def test_verify_payment_success(self, mock_verify, payment_service, test_user):
        tx = PaymentTransaction.objects.create(
            user=test_user,
            amount_fiat=Decimal("1000.00"),
            amount_skillcoins=Decimal("200.00"),
            gateway="flutterwave",
            tx_ref="tx-123",
            gateway_reference="flw-ref-123",
            status=PaymentTransaction.Status.PENDING,
        )

        mock_verify.return_value = MagicMock(
            is_successful=True,
            amount_paid=Decimal("1000.00"),
            raw_response={"status": "successful"},
        )

        payment_service.verify_payment("tx-123")

        tx.refresh_from_db()
        assert tx.status == PaymentTransaction.Status.SUCCESSFUL

        from skiflux.services.wallet_service import WalletService

        wallet = WalletService().get_or_create_wallet(test_user)
        assert wallet.balance == Decimal("200.00")

    @patch("skiflux.gateways.paystack.PaystackGateway.refund_payment")
    @patch("skiflux.gateways.paystack.PaystackGateway.verify_payment")
    def test_verify_card_add_refunds_instead_of_crediting_wallet(
        self, mock_verify, mock_refund, payment_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.default_currency = "NGN"
        config.enabled_topup_gateways = ["paystack"]
        config.save()

        CurrencyConfig.objects.create(
            currency_code="NGN",
            currency_name="Naira",
            currency_symbol="₦",
            skillcoin_rate=Decimal("1.00"),
            is_active=True,
            supported_gateways=["paystack"],
        )

        tx = PaymentTransaction.objects.create(
            user=test_user,
            amount_fiat=Decimal("50.00"),
            amount_skillcoins=Decimal("50.00"),
            currency="NGN",
            gateway="paystack",
            tx_ref="skf-card-abc123",
            gateway_reference="skf-card-abc123",
            status=PaymentTransaction.Status.PENDING,
            save_card=True,
        )

        mock_verify.return_value = MagicMock(
            is_successful=True,
            amount_paid=Decimal("50.00"),
            raw_response={
                "status": True,
                "data": {
                    "status": "success",
                    "reference": "skf-card-abc123",
                    "amount": 5000,
                    "currency": "NGN",
                    "authorization": {
                        "authorization_code": "AUTH_xyz",
                        "channel": "card",
                        "reusable": True,
                        "signature": "SIG_1",
                        "last4": "4081",
                        "exp_month": "12",
                        "exp_year": "2030",
                        "brand": "visa",
                    },
                    "customer": {"customer_code": "CUS_1"},
                },
            },
        )
        mock_refund.return_value = MagicMock(
            is_successful=True,
            refund_reference="3018284",
            raw_response={"status": True, "data": {"id": 3018284}},
        )

        payment_service.verify_payment("skf-card-abc123")

        tx.refresh_from_db()
        assert tx.status == PaymentTransaction.Status.SUCCESSFUL
        assert tx.gateway_response["card_verification_refund"]["status"] == "queued"
        mock_refund.assert_called_once()

        from skiflux.models.wallet import SavedCard
        from skiflux.services.wallet_service import WalletService

        assert SavedCard.objects.filter(user=test_user).count() == 1
        wallet = WalletService().get_or_create_wallet(test_user)
        assert wallet.balance == Decimal("0.00")

    @pytest.mark.django_db
    @patch("skiflux.gateways.paystack.PaystackGateway.verify_webhook_signature")
    def test_handle_webhook_ignores_paystack_refund_events(
        self, mock_verify_sig, payment_service
    ):
        config = SystemFinancialConfig.get_config()
        config.enabled_topup_gateways = ["paystack"]
        config.save()
        mock_verify_sig.return_value = True

        success = payment_service.handle_webhook(
            "paystack",
            {"event": "refund.pending", "data": {"status": "pending"}},
            b"{}",
            {"x-paystack-signature": "sig"},
        )

        assert success is True
