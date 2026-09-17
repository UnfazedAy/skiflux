import logging
import uuid
from decimal import Decimal
from typing import Optional

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from skiflux.gateways.registry import PaymentGatewayFactory
from skiflux.models import User
from skiflux.models.wallet import (
    PaymentTransaction,
    SavedCard,
    SystemFinancialConfig,
)
from skiflux.repositories.payment_repository import PaymentTransactionRepository

logger = logging.getLogger(__name__)
_cipher = Fernet(settings.PAYLOAD_ENCRYPTION_KEY)

CARD_TX_PREFIX = "skf-card-"


def encrypt_token(raw_token: str) -> str:
    return _cipher.encrypt(raw_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    return _cipher.decrypt(encrypted_token.encode()).decode()


def owner_kwargs(owner) -> dict:
    """Return the user/admin_user kwargs for a User or AdminUser owner."""
    if isinstance(owner, User):
        return {"user": owner, "admin_user": None}
    return {"user": None, "admin_user": owner}


class CardService:
    """Saved (tokenized) cards: adding, listing, and charging them.

    We never store card numbers — only the gateway token (encrypted) plus
    display metadata (brand, last4, expiry) for the masked rendering.
    """

    def __init__(self):
        self.payment_repo = PaymentTransactionRepository()

    # --- Add-card flow -----------------------------------------------------

    @transaction.atomic
    def initiate_add_card(
        self, owner, gateway_name: str, redirect_url: Optional[str] = None
    ) -> dict:
        config = SystemFinancialConfig.get_config()

        if gateway_name not in config.enabled_topup_gateways:
            raise ValidationError(
                f"Gateway '{gateway_name}' is not enabled for card payments."
            )

        self._enforce_max_cards(owner, config)

        gateway = PaymentGatewayFactory.get_gateway(gateway_name, purpose="topup")
        tx_ref = f"{CARD_TX_PREFIX}{uuid.uuid4().hex[:12]}"

        if gateway_name == "stripe":
            # Setup mode: no charge, Stripe returns a reusable payment method
            result = gateway.create_setup_session(
                email=owner.email, tx_ref=tx_ref, redirect_url=redirect_url
            )
            amount_fiat = Decimal("0.00")
            amount_skillcoins = Decimal("0.00")
            currency_code = "USD"
        else:
            # Charge-to-tokenize (e.g. Paystack): small charge that is
            # refunded to the card after verification, so nothing is lost.
            currency_code = config.default_currency
            curr_config = self.payment_repo.get_currency_config(currency_code)
            amount_fiat = config.card_verification_amount
            amount_skillcoins = (amount_fiat / curr_config.skillcoin_rate).quantize(
                Decimal("0.01")
            )
            result = gateway.initiate_payment(
                amount=amount_fiat,
                email=owner.email,
                tx_ref=tx_ref,
                currency=currency_code,
                redirect_url=redirect_url,
                subunit_multiplier=int(curr_config.subunit_multiplier),
                save_card=True,
                payment_method="card",
            )

        payment_tx = self.payment_repo.create(
            amount_fiat=amount_fiat,
            amount_skillcoins=amount_skillcoins,
            currency=currency_code,
            gateway=gateway_name,
            tx_ref=tx_ref,
            gateway_reference=result.gateway_reference,
            status=PaymentTransaction.Status.PENDING,
            save_card=True,
            **owner_kwargs(owner),
        )

        return {
            "transaction_id": payment_tx.id,
            "checkout_url": result.checkout_url,
            "tx_ref": tx_ref,
            "gateway": gateway_name,
            "verification_amount": str(amount_fiat),
            "currency": currency_code,
            "message": (
                "Complete the checkout to save your card. Any verification "
                "charge is refunded to your card."
            ),
        }

    def finalize_card_from_payment(
        self, payment_tx: PaymentTransaction, raw_response: dict
    ) -> Optional[SavedCard]:
        """Extract a reusable card token from a successful payment and save
        it. Non-fatal by design: a top-up must never fail because card
        tokenization did."""
        try:
            gateway = PaymentGatewayFactory.get_gateway(
                payment_tx.gateway, purpose="topup"
            )
        except ValueError:
            return None

        result = gateway.extract_card_authorization(raw_response)
        if not result or not result.reusable:
            return None

        owner = payment_tx.user or payment_tx.admin_user
        kwargs = owner_kwargs(owner)

        # Dedupe: same physical card (gateway fingerprint) updates in place
        existing = None
        if result.signature:
            existing = SavedCard.objects.filter(
                gateway_name=payment_tx.gateway,
                signature=result.signature,
                **kwargs,
            ).first()

        if existing:
            existing.token = encrypt_token(result.token)
            existing.gateway_customer_code = result.customer_code
            existing.exp_month = result.exp_month
            existing.exp_year = result.exp_year
            existing.is_active = True
            existing.save(
                update_fields=[
                    "token",
                    "gateway_customer_code",
                    "exp_month",
                    "exp_year",
                    "is_active",
                    "updated_at",
                ]
            )
            return existing

        config = SystemFinancialConfig.get_config()
        active_count = SavedCard.objects.filter(is_active=True, **kwargs).count()
        if active_count >= config.max_saved_cards:
            logger.warning(
                "Card tokenization skipped for tx %s: max saved cards reached.",
                payment_tx.tx_ref,
            )
            return None

        return SavedCard.objects.create(
            gateway_name=payment_tx.gateway,
            token=encrypt_token(result.token),
            gateway_customer_code=result.customer_code,
            card_brand=result.brand,
            last4=result.last4,
            exp_month=result.exp_month,
            exp_year=result.exp_year,
            bank_name=result.bank_name,
            card_type=result.card_type,
            currency=result.currency,
            signature=result.signature,
            is_default=(active_count == 0),
            **kwargs,
        )

    # --- Charging a saved card (one-tap top-up) ---------------------------

    @transaction.atomic
    def charge_saved_card_topup(
        self,
        owner,
        saved_card_id: str,
        amount_fiat: Decimal,
        currency: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentTransaction:
        from skiflux.services.payment_service import PaymentService

        if amount_fiat <= Decimal("0.00"):
            raise ValidationError("Top-up amount must be greater than zero.")

        if not idempotency_key:
            idempotency_key = f"auto-{uuid.uuid4().hex[:16]}"
        owner_prefix = (
            "charge_topup" if isinstance(owner, User) else "admin_charge_topup"
        )
        scoped_idempotency_key = f"{owner_prefix}_{owner.id}_{idempotency_key}"
        existing = self.payment_repo.get_by_idempotency_key(scoped_idempotency_key)
        if existing:
            return existing

        card = self._get_owned_card(owner, saved_card_id)
        if not card.is_active:
            raise ValidationError("This card has been removed.")

        config = SystemFinancialConfig.get_config()
        if card.gateway_name not in config.enabled_topup_gateways:
            raise ValidationError(
                f"Gateway '{card.gateway_name}' is not enabled for top-ups."
            )

        currency_code = currency or config.default_currency
        curr_config = self.payment_repo.get_currency_config(currency_code)
        amount_skillcoins = (amount_fiat / curr_config.skillcoin_rate).quantize(
            Decimal("0.01")
        )

        gateway = PaymentGatewayFactory.get_gateway(card.gateway_name, purpose="topup")

        if config.pass_gateway_fees_to_customer:
            gateway_fee = gateway.calculate_fee(amount_fiat, currency_code)
            charged_amount = (amount_fiat + gateway_fee).quantize(Decimal("0.01"))
        else:
            charged_amount = amount_fiat

        tx_ref = f"skf-topup-{uuid.uuid4().hex[:12]}"
        payment_tx = self.payment_repo.create(
            amount_fiat=amount_fiat,
            amount_skillcoins=amount_skillcoins,
            currency=currency_code,
            gateway=card.gateway_name,
            tx_ref=tx_ref,
            status=PaymentTransaction.Status.INITIATED,
            idempotency_key=scoped_idempotency_key,
            **owner_kwargs(owner),
        )

        try:
            result = gateway.charge_card_token(
                token=decrypt_token(card.token),
                customer_code=card.gateway_customer_code,
                email=owner.email,
                amount=charged_amount,
                tx_ref=tx_ref,
                currency=currency_code,
                subunit_multiplier=int(curr_config.subunit_multiplier),
            )
        except Exception as e:
            payment_tx.status = PaymentTransaction.Status.FAILED
            payment_tx.gateway_response = {"error": str(e)}
            payment_tx.save(update_fields=["status", "gateway_response", "updated_at"])
            raise

        payment_tx.gateway_reference = result.gateway_reference
        payment_tx.gateway_response = result.raw_response

        if result.is_successful:
            PaymentService()._credit_payment_transaction(
                payment_tx, PaymentTransaction.Status.INITIATED
            )
        else:
            payment_tx.status = PaymentTransaction.Status.FAILED
            payment_tx.save(
                update_fields=[
                    "status",
                    "gateway_reference",
                    "gateway_response",
                    "updated_at",
                ]
            )
            raise ValidationError("Card charge was not successful.")

        return payment_tx

    # --- Card management ---------------------------------------------------

    def list_cards(self, owner):
        return SavedCard.objects.filter(is_active=True, **owner_kwargs(owner)).order_by(
            "-is_default", "-created_at"
        )

    @transaction.atomic
    def deactivate_card(self, owner, saved_card_id: str) -> SavedCard:
        card = self._get_owned_card(owner, saved_card_id)
        card.is_active = False
        card.is_default = False
        card.save(update_fields=["is_active", "is_default", "updated_at"])
        return card

    @transaction.atomic
    def set_default_card(self, owner, saved_card_id: str) -> SavedCard:
        card = self._get_owned_card(owner, saved_card_id)
        if not card.is_active:
            raise ValidationError("This card has been removed.")
        SavedCard.objects.filter(**owner_kwargs(owner)).update(
            is_default=False, updated_at=timezone.now()
        )
        card.is_default = True
        card.save(update_fields=["is_default", "updated_at"])
        return card

    # --- Helpers -----------------------------------------------------------

    def _get_owned_card(self, owner, saved_card_id: str) -> SavedCard:
        card = SavedCard.objects.filter(id=saved_card_id, **owner_kwargs(owner)).first()
        if not card:
            raise ValidationError("Saved card not found.")
        return card

    def _enforce_max_cards(self, owner, config) -> None:
        active_count = SavedCard.objects.filter(
            is_active=True, **owner_kwargs(owner)
        ).count()
        if active_count >= config.max_saved_cards:
            raise ValidationError(
                f"Maximum of {config.max_saved_cards} saved cards allowed."
            )
