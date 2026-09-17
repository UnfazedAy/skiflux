import json
import logging
import uuid
from decimal import Decimal

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from skiflux.gateways.payment_channels import TOPUP_PAYMENT_METHOD_BANK_TRANSFER
from skiflux.gateways.registry import PaymentGatewayFactory
from skiflux.models import User
from skiflux.models.wallet import (
    PaymentTransaction,
    SkillcoinTransaction,
    SystemFinancialConfig,
)
from skiflux.repositories.payment_repository import PaymentTransactionRepository
from skiflux.services.card_service import CARD_TX_PREFIX
from skiflux.services.wallet_service import WalletService
from skiflux.utils.exceptions import PaymentVerificationError

logger = logging.getLogger(__name__)
_cipher = Fernet(settings.PAYLOAD_ENCRYPTION_KEY)


class PayloadEncryptor:
    @staticmethod
    def decrypt_json(encrypted_data: str) -> dict:
        if not encrypted_data:
            return {}
        try:
            decrypted = _cipher.decrypt(encrypted_data.encode())
            return json.loads(decrypted.decode())
        except Exception as e:
            logger.error(f"Decryption error: {str(e)}")
            return {}


class PaymentService:
    def __init__(self):
        self.wallet_service = WalletService()
        self.payment_repo = PaymentTransactionRepository()

    @transaction.atomic
    def initiate_topup(
        self,
        user,
        amount_fiat: Decimal,
        idempotency_key: str = None,
        gateway_name: str = None,
        currency: str = None,
        redirect_url: str = None,
        save_card: bool = False,
        payment_method: str = "all",
        **kwargs,
    ) -> dict:
        """Initiate a wallet top-up for a User or AdminUser owner."""
        from skiflux.services.card_service import owner_kwargs

        owner_fields = owner_kwargs(user)
        if not idempotency_key:
            idempotency_key = kwargs.get("idempotency_key")
        if not idempotency_key:
            idempotency_key = f"auto-{uuid.uuid4().hex[:16]}"
        if payment_method == TOPUP_PAYMENT_METHOD_BANK_TRANSFER and save_card:
            raise ValidationError(
                "save_card is only supported when payment_method is card or all."
            )
        owner_prefix = "topup" if isinstance(user, User) else "admin_topup"
        scoped_idempotency_key = f"{owner_prefix}_{user.id}_{idempotency_key}"
        existing = self.payment_repo.get_by_idempotency_key(scoped_idempotency_key)
        backend_callback_url = (
            redirect_url
            if redirect_url
            else getattr(
                settings,
                "PAYMENT_REDIRECT_URL",
                f"{settings.PUBLIC_API_BASE_URL}/api/v1/wallet/topup/verify",
            )
        )

        if existing:
            decrypted_data = PayloadEncryptor.decrypt_json(
                existing.gateway_response.get("encrypted_data", "")
            )
            return {
                "transaction_id": existing.id,
                "checkout_url": decrypted_data.get("checkout_url"),
                "tx_ref": existing.tx_ref,
                "gateway_reference": existing.gateway_reference,
                "gateway": existing.gateway,
                "message": "Retrieved existing transaction",
            }

        config = SystemFinancialConfig.get_config()
        currency_code = currency or config.default_currency

        try:
            from skiflux.models.currency import CurrencyConfig

            curr_config = self.payment_repo.get_currency_config(currency_code)
        except CurrencyConfig.DoesNotExist:
            raise ValidationError(
                f"Currency '{currency_code}' is not supported or active."
            )

        if not gateway_name:
            if curr_config.supported_gateways:
                gateway_name = curr_config.supported_gateways[0]
            else:
                raise ValidationError(
                    f"No active gateways found for currency {currency_code}."
                )

        if gateway_name not in config.enabled_topup_gateways:
            raise ValidationError(
                f"Gateway '{gateway_name}' is not globally enabled for top-ups."
            )

        if (
            payment_method == TOPUP_PAYMENT_METHOD_BANK_TRANSFER
            and gateway_name == "stripe"
        ):
            raise ValidationError("Bank transfer is not supported for Stripe top-ups.")

        if amount_fiat <= Decimal("0.00"):
            raise ValidationError("Top-up amount must be greater than zero.")

        # --- Duplicate check: same user, amount, currency, gateway, still active ---
        duplicate = self.payment_repo.find_pending_duplicate(
            owner=user,
            amount_fiat=amount_fiat,
            currency=currency_code,
            gateway=gateway_name,
        )
        if duplicate and duplicate.gateway_response:
            decrypted_data = PayloadEncryptor.decrypt_json(
                duplicate.gateway_response.get("encrypted_data", "")
            )
            checkout_url = decrypted_data.get("checkout_url")
            if checkout_url:
                return {
                    "transaction_id": duplicate.id,
                    "checkout_url": checkout_url,
                    "tx_ref": duplicate.tx_ref,
                    "gateway_reference": duplicate.gateway_reference,
                    "gateway": duplicate.gateway,
                    "message": "Existing pending transaction returned",
                }

        rate = curr_config.skillcoin_rate
        amount_skillcoins = (amount_fiat / rate).quantize(Decimal("0.01"))

        tx_ref = f"skf-topup-{uuid.uuid4().hex[:12]}"

        payment_tx = self.payment_repo.create(
            amount_fiat=amount_fiat,
            amount_skillcoins=amount_skillcoins,
            currency=currency_code,
            gateway=gateway_name,
            tx_ref=tx_ref,
            status=PaymentTransaction.Status.INITIATED,
            idempotency_key=scoped_idempotency_key,
            save_card=save_card,
            **owner_fields,
        )
        self.payment_repo.create_status_event(
            payment_transaction=payment_tx,
            from_status=None,
            to_status=PaymentTransaction.Status.INITIATED,
            reason="Payment initiated",
            actor=user.email,
        )

        gateway = PaymentGatewayFactory.get_gateway(gateway_name)
        try:
            # --- Fee pass-through: charge customer if enabled ---
            if config.pass_gateway_fees_to_customer:
                gateway_fee = gateway.calculate_fee(amount_fiat, currency_code)
                charged_amount = (amount_fiat + gateway_fee).quantize(Decimal("0.01"))
            else:
                gateway_fee = Decimal("0.00")
                charged_amount = amount_fiat

            result = gateway.initiate_payment(
                amount=charged_amount,
                email=user.email,
                tx_ref=tx_ref,
                currency=currency_code,
                redirect_url=backend_callback_url,
                subunit_multiplier=int(curr_config.subunit_multiplier),
                save_card=save_card,
                payment_method=payment_method,
            )
            encrypted_response = _cipher.encrypt(
                json.dumps({"checkout_url": result.checkout_url}).encode()
            )
            payment_tx.gateway_reference = result.gateway_reference
            payment_tx.status = PaymentTransaction.Status.PENDING
            if not payment_tx.gateway_response:
                payment_tx.gateway_response = {}
            payment_tx.gateway_response = {
                "encrypted_data": encrypted_response.decode()
            }
            payment_tx.save(
                update_fields=[
                    "gateway_reference",
                    "status",
                    "gateway_response",
                    "updated_at",
                ]
            )

            self.payment_repo.create_status_event(
                payment_transaction=payment_tx,
                from_status=PaymentTransaction.Status.INITIATED,
                to_status=PaymentTransaction.Status.PENDING,
                reason="Gateway initiation successful",
                actor="system",
            )

            return {
                "transaction_id": payment_tx.id,
                "checkout_url": result.checkout_url,
                "tx_ref": tx_ref,
                "gateway_reference": payment_tx.gateway_reference,
                "gateway": gateway_name,
                "amount_fiat": str(amount_fiat),
                "gateway_fee": str(gateway_fee),
                "charged_amount": str(charged_amount),
                "currency": currency_code,
            }
        except Exception as e:
            payment_tx.status = PaymentTransaction.Status.FAILED
            payment_tx.gateway_response = {"error": str(e)}
            payment_tx.save(update_fields=["status", "gateway_response", "updated_at"])
            self.payment_repo.create_status_event(
                payment_transaction=payment_tx,
                from_status=PaymentTransaction.Status.INITIATED,
                to_status=PaymentTransaction.Status.FAILED,
                reason=f"Gateway initiation failed: {str(e)}",
                actor="system",
            )
            raise

    def get_topup_methods(self) -> list:
        """Active top-up currencies and the gateways that support them —
        drives the frontend's 'add money' screen with no hardcoding."""
        from skiflux.models.currency import CurrencyConfig

        config = SystemFinancialConfig.get_config()
        methods = []
        for curr in CurrencyConfig.objects.filter(is_active=True).order_by(
            "currency_code"
        ):
            gateways = [
                g
                for g in (curr.supported_gateways or [])
                if g in config.enabled_topup_gateways
            ]
            if not gateways:
                continue
            methods.append(
                {
                    "currency_code": curr.currency_code,
                    "currency_name": curr.currency_name,
                    "currency_symbol": curr.currency_symbol,
                    "skillcoin_rate": str(curr.skillcoin_rate),
                    "gateways": gateways,
                    "is_default": curr.currency_code == config.default_currency,
                }
            )
        return methods

    @transaction.atomic
    def verify_payment(
        self,
        tx_ref: str,
        requesting_user=None,
        gateway_reference: str = None,
    ) -> PaymentTransaction:
        payment_tx = self.payment_repo.get_by_tx_ref(tx_ref, lock=True)
        if not payment_tx:
            raise PaymentVerificationError("Payment transaction not found.")

        if requesting_user:
            if isinstance(requesting_user, User):
                is_owner = payment_tx.user_id == requesting_user.id
            else:
                is_owner = payment_tx.admin_user_id == requesting_user.id
            if not is_owner:
                raise PaymentVerificationError(
                    "You do not have permission to verify this transaction."
                )

        if payment_tx.status == PaymentTransaction.Status.SUCCESSFUL:
            return payment_tx

        gateway = PaymentGatewayFactory.get_gateway(payment_tx.gateway)
        ref_to_verify = gateway_reference or payment_tx.gateway_reference
        if not ref_to_verify:
            raise ValidationError("No gateway reference available for verification.")

        result = gateway.verify_payment(ref_to_verify)

        # Keep checkout_url if it exists
        if (
            payment_tx.gateway_response
            and "checkout_url" in payment_tx.gateway_response
        ):
            result.raw_response["checkout_url"] = payment_tx.gateway_response[
                "checkout_url"
            ]

        payment_tx.gateway_response = result.raw_response

        old_status = payment_tx.status
        if result.is_successful and result.amount_paid >= payment_tx.amount_fiat:
            self._credit_payment_transaction(
                payment_tx, old_status, raw_response=result.raw_response
            )
        else:
            payment_tx.status = PaymentTransaction.Status.FAILED
            payment_tx.save(update_fields=["status", "gateway_response", "updated_at"])
            self.payment_repo.create_status_event(
                payment_transaction=payment_tx,
                from_status=old_status,
                to_status=PaymentTransaction.Status.FAILED,
                reason="Payment verification failed or insufficient amount",
                actor="system",
            )
            logger.warning(f"Topup failed for tx_ref {tx_ref}.")

        return payment_tx

    def _credit_payment_transaction(
        self,
        payment_tx: PaymentTransaction,
        old_status,
        raw_response: dict = None,
    ) -> None:
        """Mark a PaymentTransaction as SUCCESSFUL and credit the user's wallet.

        This is shared by both verify_payment (manual verify endpoint) and
        handle_webhook (automatic webhook credit), so the crediting logic
        lives in exactly one place.
        """
        tx_ref = payment_tx.tx_ref
        is_card_verification = tx_ref.startswith(CARD_TX_PREFIX)
        payment_tx.status = PaymentTransaction.Status.SUCCESSFUL
        payment_tx.verified_at = timezone.now()
        payment_tx.save(
            update_fields=[
                "status",
                "verified_at",
                "gateway_reference",
                "gateway_response",
                "updated_at",
            ]
        )
        self.payment_repo.create_status_event(
            payment_transaction=payment_tx,
            from_status=old_status,
            to_status=PaymentTransaction.Status.SUCCESSFUL,
            reason="Payment verified successfully",
            actor="system",
        )
        # Card verification charges are refunded to the card, not credited
        # to the wallet. Real top-ups (skf-topup-*) credit Skillcoins.
        if payment_tx.amount_skillcoins > Decimal("0.00") and not is_card_verification:
            self.wallet_service.credit_wallet(
                owner=payment_tx.user or payment_tx.admin_user,
                amount=payment_tx.amount_skillcoins,
                tx_type=SkillcoinTransaction.Type.TOPUP,
                description=f"Wallet Top-up via {payment_tx.gateway} (Ref: {tx_ref})",
                reference_id=payment_tx.id,
                idempotency_key=f"topup-{payment_tx.id}",
            )
            logger.info(
                f"Topup successful for tx_ref {tx_ref}. Credited {payment_tx.amount_skillcoins} skillcoins."  # noqa: E501
            )
        if payment_tx.user and not is_card_verification:
            from skiflux.utils.platform_task_tracker import trigger_platform_task

            trigger_platform_task(payment_tx.user, "first_deposit")

        # Tokenize and save the card used for this payment when requested.
        # Non-fatal: a top-up must never fail because tokenization did.
        if payment_tx.save_card and raw_response:
            try:
                from skiflux.services.card_service import CardService

                saved_card = CardService().finalize_card_from_payment(
                    payment_tx, raw_response
                )
                if saved_card is None:
                    logger.warning(
                        "Card tokenization returned no saved card for tx_ref %s.",
                        tx_ref,
                    )
            except Exception:
                logger.warning(
                    f"Card tokenization failed for tx_ref {tx_ref} (non-fatal)",
                    exc_info=True,
                )

        if is_card_verification:
            self._refund_card_verification_charge(payment_tx, raw_response)

    def _refund_card_verification_charge(
        self, payment_tx: PaymentTransaction, raw_response: dict = None
    ) -> None:
        """Return a Paystack card-verification charge to the customer's card."""
        if payment_tx.gateway != "paystack" or payment_tx.amount_fiat <= Decimal(
            "0.00"
        ):
            return

        existing_refund = (payment_tx.gateway_response or {}).get(
            "card_verification_refund"
        )
        if existing_refund and existing_refund.get("status") == "queued":
            return

        tx_data = (raw_response or {}).get("data", {}) if raw_response else {}
        transaction_reference = (
            tx_data.get("reference")
            or payment_tx.gateway_reference
            or payment_tx.tx_ref
        )
        if not transaction_reference:
            logger.error(
                "Card verification refund skipped for tx_ref %s: no transaction reference.",  # noqa: E501
                payment_tx.tx_ref,
            )
            return

        try:
            gateway = PaymentGatewayFactory.get_gateway("paystack", purpose="topup")
            curr_config = self.payment_repo.get_currency_config(payment_tx.currency)
            result = gateway.refund_payment(
                transaction_reference=transaction_reference,
                amount=payment_tx.amount_fiat,
                currency=payment_tx.currency,
                subunit_multiplier=int(curr_config.subunit_multiplier),
                customer_note=(f"Card verification refund for {payment_tx.tx_ref}"),
                merchant_note=(
                    f"Automatic card-save verification refund ({payment_tx.tx_ref})"
                ),
            )
            refund_record = {
                "status": "queued" if result.is_successful else "failed",
                "refund_reference": result.refund_reference,
                "raw_response": result.raw_response,
            }
            if result.is_successful:
                logger.info(
                    "Card verification refund queued for tx_ref %s (refund %s).",
                    payment_tx.tx_ref,
                    result.refund_reference,
                )
            else:
                logger.error(
                    "Card verification refund failed for tx_ref %s.",
                    payment_tx.tx_ref,
                )
        except Exception:
            refund_record = {"status": "failed", "error": "refund_request_failed"}
            logger.warning(
                "Card verification refund request failed for tx_ref %s (non-fatal).",
                payment_tx.tx_ref,
                exc_info=True,
            )

        gateway_response = dict(payment_tx.gateway_response or {})
        gateway_response["card_verification_refund"] = refund_record
        payment_tx.gateway_response = gateway_response
        payment_tx.save(update_fields=["gateway_response", "updated_at"])

    @transaction.atomic
    def handle_webhook(
        self, gateway_name: str, payload: dict, raw_body: bytes, headers
    ) -> bool:
        """Process an inbound payment gateway webhook.

        The webhook payload is treated as the source of truth — we parse it
        directly instead of making a second API call to the gateway, which
        would be slow and fragile (especially in test/staging environments).
        """
        gateway = PaymentGatewayFactory.get_gateway(gateway_name)
        if not gateway.verify_webhook_signature(raw_body, headers, payload):
            logger.error(f"Invalid webhook signature for gateway {gateway_name}")
            return False

        event = payload.get("event", "")
        if gateway_name == "paystack" and event.startswith("refund."):
            # Paystack sends refund.* after we queue card-verification refunds.
            # Informational only — the original charge.success already finalized
            # the payment/card save.
            logger.info(
                "Ignoring Paystack refund webhook event=%s (informational).",
                event,
            )
            return True

        try:
            webhook_data = gateway.parse_webhook_payload(payload)

            if not webhook_data.tx_ref:
                logger.warning(
                    f"Webhook from {gateway_name} missing tx_ref — skipping."
                )
                return False

            # Only process top-up and card-save references
            # (skip withdrawal references)
            if not webhook_data.tx_ref.startswith(("skf-topup-", "skf-card-")):
                logger.info(
                    f"Webhook tx_ref {webhook_data.tx_ref} is not a top-up — ignoring."
                )
                return True

            payment_tx = self.payment_repo.get_by_tx_ref(webhook_data.tx_ref, lock=True)
            if not payment_tx:
                logger.error(
                    f"Webhook: PaymentTransaction not found for tx_ref {webhook_data.tx_ref}"  # noqa: E501
                )
                return False

            # Idempotency: wallet already credited — still try card save if needed
            if payment_tx.status == PaymentTransaction.Status.SUCCESSFUL:
                if payment_tx.save_card and gateway_name == "stripe":
                    try:
                        from skiflux.services.card_service import CardService

                        CardService().finalize_card_from_payment(payment_tx, payload)
                    except Exception:
                        logger.warning(
                            "Card tokenization retry failed for tx_ref %s (non-fatal)",
                            webhook_data.tx_ref,
                            exc_info=True,
                        )
                logger.info(
                    f"Webhook: tx_ref {webhook_data.tx_ref} already SUCCESSFUL — skipping."  # noqa: E501
                )
                return True

            if not webhook_data.is_successful:
                old_status = payment_tx.status
                payment_tx.status = PaymentTransaction.Status.FAILED
                payment_tx.save(update_fields=["status", "updated_at"])
                self.payment_repo.create_status_event(
                    payment_transaction=payment_tx,
                    from_status=old_status,
                    to_status=PaymentTransaction.Status.FAILED,
                    reason="Payment failed per webhook notification",
                    actor="webhook",
                )
                logger.warning(
                    f"Webhook: tx_ref {webhook_data.tx_ref} failed per gateway notification."  # noqa: E501
                )
                return True

            # Validate amount: webhook amount must cover the expected fiat amount
            if webhook_data.amount_paid < payment_tx.amount_fiat:
                logger.error(
                    f"Webhook: amount mismatch for {webhook_data.tx_ref}: "  # noqa: E501
                    f"expected >={payment_tx.amount_fiat}, got {webhook_data.amount_paid}"  # noqa: E501
                )
                return False

            # Store the gateway_reference if not already set
            if not payment_tx.gateway_reference and webhook_data.gateway_reference:  # noqa: E501
                payment_tx.gateway_reference = webhook_data.gateway_reference

            old_status = payment_tx.status
            self._credit_payment_transaction(
                payment_tx, old_status, raw_response=payload
            )
            return True

        except Exception as e:
            logger.error(
                f"Error handling webhook for {gateway_name}: {str(e)}", exc_info=True
            )

        return False
