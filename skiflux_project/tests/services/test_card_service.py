from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.exceptions import ValidationError

from skiflux.models import User
from skiflux.models.currency import CurrencyConfig
from skiflux.models.wallet import (
    PaymentTransaction,
    SavedCard,
    SystemFinancialConfig,
)
from skiflux.services.card_service import CardService, decrypt_token


@pytest.fixture
def card_service():
    return CardService()


@pytest.fixture
def test_user(db):
    return User.objects.create(email="cardholder@test.com", password="pwd")


@pytest.fixture
def paystack_config(db):
    config = SystemFinancialConfig.get_config()
    config.default_currency = "NGN"
    config.enabled_topup_gateways = ["paystack"]
    config.max_saved_cards = 3
    config.card_verification_amount = Decimal("50.00")
    config.save()
    CurrencyConfig.objects.create(
        currency_code="NGN",
        currency_name="Naira",
        currency_symbol="₦",
        skillcoin_rate=Decimal("1.00"),
        is_active=True,
        supported_gateways=["paystack"],
    )
    return config


def paystack_verify_payload(reusable=True, signature="SIG_abc123"):
    """A realistic (abridged) Paystack verify/webhook payload."""
    return {
        "status": True,
        "data": {
            "status": "success",
            "reference": "skf-card-abc",
            "amount": 5000,
            "currency": "NGN",
            "channel": "card",
            "authorization": {
                "authorization_code": "AUTH_xyz789",
                "card_type": "visa ",
                "last4": "4081",
                "exp_month": "12",
                "exp_year": "2030",
                "channel": "card",
                "bank": "TEST BANK",
                "brand": "visa",
                "reusable": reusable,
                "signature": signature,
            },
            "customer": {"customer_code": "CUS_123", "email": "cardholder@test.com"},
        },
    }


@pytest.mark.django_db
class TestCardTokenization:
    def _card_payment_tx(self, user):
        return PaymentTransaction.objects.create(
            user=user,
            amount_fiat=Decimal("50.00"),
            amount_skillcoins=Decimal("50.00"),
            currency="NGN",
            gateway="paystack",
            tx_ref="skf-card-abc",
            status=PaymentTransaction.Status.PENDING,
            save_card=True,
        )

    def test_finalize_card_from_paystack_payload(
        self, card_service, test_user, paystack_config
    ):
        tx = self._card_payment_tx(test_user)

        card = card_service.finalize_card_from_payment(tx, paystack_verify_payload())

        assert card is not None
        assert card.user == test_user
        assert card.gateway_name == "paystack"
        assert card.last4 == "4081"
        assert card.card_brand == "visa"
        assert card.masked_number == "**** **** **** 4081"
        assert card.is_default is True
        # Token is encrypted at rest but decrypts to the authorization code
        assert card.token != "AUTH_xyz789"
        assert decrypt_token(card.token) == "AUTH_xyz789"

    def test_finalize_dedupes_same_card_by_signature(
        self, card_service, test_user, paystack_config
    ):
        tx = self._card_payment_tx(test_user)

        first = card_service.finalize_card_from_payment(tx, paystack_verify_payload())
        second = card_service.finalize_card_from_payment(tx, paystack_verify_payload())

        assert first.id == second.id
        assert SavedCard.objects.filter(user=test_user).count() == 1

    def test_non_reusable_card_is_not_saved(
        self, card_service, test_user, paystack_config
    ):
        tx = self._card_payment_tx(test_user)

        card = card_service.finalize_card_from_payment(
            tx, paystack_verify_payload(reusable=False)
        )

        assert card is None
        assert SavedCard.objects.count() == 0

    def test_max_saved_cards_blocks_add_card(
        self, card_service, test_user, paystack_config
    ):
        paystack_config.max_saved_cards = 1
        paystack_config.save()
        SavedCard.objects.create(
            user=test_user,
            gateway_name="paystack",
            token="enc",
            last4="1111",
            is_active=True,
        )

        with pytest.raises(ValidationError, match="Maximum of 1 saved cards"):
            card_service.initiate_add_card(test_user, "paystack")

    @patch("skiflux.gateways.paystack.PaystackGateway.initiate_payment")
    def test_initiate_add_card_paystack(
        self, mock_initiate, card_service, test_user, paystack_config
    ):
        mock_initiate.return_value = MagicMock(
            checkout_url="https://paystack.com/pay/xyz",
            gateway_reference="ps-ref-1",
        )

        result = card_service.initiate_add_card(test_user, "paystack")

        assert result["checkout_url"] == "https://paystack.com/pay/xyz"
        assert result["tx_ref"].startswith("skf-card-")
        tx = PaymentTransaction.objects.get(tx_ref=result["tx_ref"])
        assert tx.save_card is True
        assert tx.amount_fiat == Decimal("50.00")
        # The gateway was asked to make the card reusable
        assert mock_initiate.call_args.kwargs["save_card"] is True


@pytest.mark.django_db
class TestChargeSavedCard:
    @patch("skiflux.gateways.paystack.PaystackGateway.charge_card_token")
    def test_charge_saved_card_credits_wallet(
        self, mock_charge, card_service, test_user, paystack_config
    ):
        card = card_service.finalize_card_from_payment(
            PaymentTransaction.objects.create(
                user=test_user,
                amount_fiat=Decimal("50.00"),
                amount_skillcoins=Decimal("50.00"),
                currency="NGN",
                gateway="paystack",
                tx_ref="skf-card-seed",
                status=PaymentTransaction.Status.SUCCESSFUL,
                save_card=True,
            ),
            paystack_verify_payload(),
        )
        mock_charge.return_value = MagicMock(
            is_successful=True,
            gateway_reference="ps-charge-1",
            raw_response={"status": True},
        )

        tx = card_service.charge_saved_card_topup(
            test_user, str(card.id), Decimal("1000.00")
        )

        assert tx.status == PaymentTransaction.Status.SUCCESSFUL
        assert mock_charge.call_args.kwargs["token"] == "AUTH_xyz789"

        from skiflux.services.wallet_service import WalletService

        wallet = WalletService().get_or_create_wallet(test_user)
        assert wallet.balance == Decimal("1000.00")

    @patch("skiflux.gateways.paystack.PaystackGateway.charge_card_token")
    def test_charge_saved_card_idempotency(
        self, mock_charge, card_service, test_user, paystack_config
    ):
        card = card_service.finalize_card_from_payment(
            PaymentTransaction.objects.create(
                user=test_user,
                amount_fiat=Decimal("50.00"),
                amount_skillcoins=Decimal("50.00"),
                currency="NGN",
                gateway="paystack",
                tx_ref="skf-card-idemp",
                status=PaymentTransaction.Status.SUCCESSFUL,
                save_card=True,
            ),
            paystack_verify_payload(),
        )
        mock_charge.return_value = MagicMock(
            is_successful=True,
            gateway_reference="ps-charge-1",
            raw_response={"status": True},
        )

        first = card_service.charge_saved_card_topup(
            test_user,
            str(card.id),
            Decimal("500.00"),
            idempotency_key="client-key-1",
        )
        second = card_service.charge_saved_card_topup(
            test_user,
            str(card.id),
            Decimal("500.00"),
            idempotency_key="client-key-1",
        )

        assert first.id == second.id
        mock_charge.assert_called_once()

    @patch("skiflux.gateways.paystack.PaystackGateway.charge_card_token")
    def test_charge_unknown_card_rejected(
        self, mock_charge, card_service, test_user, paystack_config
    ):
        import uuid

        with pytest.raises(ValidationError, match="Saved card not found"):
            card_service.charge_saved_card_topup(
                test_user, str(uuid.uuid4()), Decimal("100.00")
            )

    def test_deactivated_card_cannot_be_charged(
        self, card_service, test_user, paystack_config
    ):
        card = SavedCard.objects.create(
            user=test_user,
            gateway_name="paystack",
            token="enc",
            last4="1111",
            is_active=True,
        )
        card_service.deactivate_card(test_user, str(card.id))

        with pytest.raises(ValidationError, match="This card has been removed"):
            card_service.charge_saved_card_topup(
                test_user, str(card.id), Decimal("100.00")
            )

        assert card_service.list_cards(test_user).count() == 0
