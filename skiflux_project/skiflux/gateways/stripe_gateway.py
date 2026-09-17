from decimal import Decimal
from typing import Optional

import stripe
from django.conf import settings
from rest_framework.exceptions import ValidationError

from .base import (
    ChargeTokenResult,
    InitiatePaymentResult,
    InitiateTransferResult,
    PaymentGateway,
    ResolveAccountResult,
    TokenizeCardResult,
    VerifyPaymentResult,
    WebhookPaymentData,
)


class StripeGateway(PaymentGateway):
    def __init__(self):
        self.secret_key = getattr(settings, "STRIPE_SECRET_KEY", "")
        self.webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        stripe.api_key = self.secret_key

    @property
    def name(self) -> str:
        return "stripe"

    def initiate_payment(
        self,
        amount: Decimal,
        email: str,
        tx_ref: str,
        currency: str = "USD",
        redirect_url: Optional[str] = None,
        subunit_multiplier: int = 100,
        save_card: bool = False,
        payment_method: str = "all",
    ) -> InitiatePaymentResult:
        if not redirect_url:
            redirect_url = getattr(settings, "PAYMENT_REDIRECT_URL", "")

        # Convert to smallest currency unit (e.g. cents for USD)
        amount_smallest_unit = int(amount * subunit_multiplier)

        try:
            session_kwargs = {
                "payment_method_types": ["card"],
                "line_items": [
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "product_data": {
                                "name": "SkillFlux Wallet Top-up",
                            },
                            "unit_amount": amount_smallest_unit,
                        },
                        "quantity": 1,
                    }
                ],
                "mode": "payment",
                "success_url": f"{redirect_url}?status=success&tx_ref={tx_ref}",
                "cancel_url": f"{redirect_url}?status=cancel&tx_ref={tx_ref}",
                "customer_email": email,
                "client_reference_id": tx_ref,
            }
            if save_card:
                # Attach the card to a customer for future off-session use
                session_kwargs.pop("customer_email")
                session_kwargs["customer"] = stripe.Customer.create(email=email).id
                session_kwargs["payment_intent_data"] = {
                    "setup_future_usage": "off_session"
                }
            session = stripe.checkout.Session.create(**session_kwargs)

            return InitiatePaymentResult(
                gateway_reference=session.id,
                checkout_url=session.url,
                raw_response=session,
            )
        except stripe.StripeError as e:
            raise ValidationError(f"Payment initiation failed: {str(e)}")
        except Exception:
            raise ValidationError("Could not connect to payment gateway")

    def verify_payment(self, gateway_reference: str) -> VerifyPaymentResult:
        try:
            # We assume gateway_reference is the checkout session id
            if gateway_reference.startswith("cs_"):
                session = stripe.checkout.Session.retrieve(gateway_reference)
                payment_intent_id = session.payment_intent
                if not payment_intent_id:
                    # Could be unpaid, or a setup-mode session (card save,
                    # no charge) which reports "no_payment_required".
                    return VerifyPaymentResult(
                        is_successful=session.payment_status
                        in ("paid", "no_payment_required"),
                        amount_paid=Decimal(str(session.amount_total)) / 100
                        if session.amount_total
                        else Decimal(0),
                        currency=session.currency.upper()
                        if session.currency
                        else "USD",
                        gateway_reference=session.id,
                        raw_response=session,
                    )

                pi = stripe.PaymentIntent.retrieve(payment_intent_id)
                is_successful = pi.status == "succeeded"
                amount_paid = Decimal(str(pi.amount_received)) / 100
                currency = pi.currency.upper()
                return VerifyPaymentResult(
                    is_successful=is_successful,
                    amount_paid=amount_paid,
                    currency=currency,
                    gateway_reference=session.id,
                    raw_response=pi,
                )
            elif gateway_reference.startswith("pi_"):
                pi = stripe.PaymentIntent.retrieve(gateway_reference)
                is_successful = pi.status == "succeeded"
                amount_paid = Decimal(str(pi.amount_received)) / 100
                currency = pi.currency.upper()
                return VerifyPaymentResult(
                    is_successful=is_successful,
                    amount_paid=amount_paid,
                    currency=currency,
                    gateway_reference=pi.id,
                    raw_response=pi,
                )
            else:
                raise ValidationError("Invalid gateway reference format for Stripe.")
        except stripe.StripeError as e:
            raise ValidationError(f"Verification failed: {str(e)}")

    # --- Saved cards (tokenization) --------------------------------------

    def create_setup_session(
        self,
        email: str,
        tx_ref: str,
        redirect_url: Optional[str] = None,
    ) -> InitiatePaymentResult:
        """Create a Stripe-hosted Checkout Session in setup mode. The user
        enters their card once; Stripe returns a reusable payment method
        attached to a customer — no charge is made."""
        if not redirect_url:
            redirect_url = getattr(settings, "PAYMENT_REDIRECT_URL", "")
        try:
            customer = stripe.Customer.create(email=email)
            session = stripe.checkout.Session.create(
                mode="setup",
                payment_method_types=["card"],
                customer=customer.id,
                success_url=f"{redirect_url}?status=success&tx_ref={tx_ref}",
                cancel_url=f"{redirect_url}?status=cancel&tx_ref={tx_ref}",
                client_reference_id=tx_ref,
                setup_intent_data={"metadata": {"tx_ref": tx_ref}},
            )
            return InitiatePaymentResult(
                gateway_reference=session.id,
                checkout_url=session.url,
                raw_response=session,
            )
        except stripe.StripeError as e:
            raise ValidationError(f"Card setup initiation failed: {str(e)}")

    def extract_card_authorization(self, raw_response: dict):
        """Extract a reusable card from a Stripe Checkout Session /
        PaymentIntent payload (verify response or webhook object)."""
        try:
            obj = raw_response
            if hasattr(obj, "to_dict"):
                obj = obj.to_dict()
            if isinstance(obj, dict) and obj.get("object") == "event":
                obj = obj.get("data", {}).get("object", {})

            payment_method_id = None
            customer_id = ""

            def _stripe_id(value):
                if not value:
                    return ""
                if isinstance(value, str):
                    return value
                if isinstance(value, dict):
                    return value.get("id", "")
                return getattr(value, "id", "")

            if obj.get("object") == "checkout.session":
                customer_id = _stripe_id(obj.get("customer"))
                if obj.get("mode") == "setup" and obj.get("setup_intent"):
                    si = stripe.SetupIntent.retrieve(_stripe_id(obj["setup_intent"]))
                    payment_method_id = _stripe_id(si.get("payment_method"))
                    customer_id = customer_id or _stripe_id(si.get("customer"))
                elif obj.get("payment_intent"):
                    pi = stripe.PaymentIntent.retrieve(
                        _stripe_id(obj["payment_intent"])
                    )
                    if pi.get("setup_future_usage"):
                        payment_method_id = _stripe_id(pi.get("payment_method"))
                        customer_id = customer_id or _stripe_id(pi.get("customer"))
            elif obj.get("object") == "setup_intent":
                if obj.get("status") == "succeeded":
                    payment_method_id = _stripe_id(obj.get("payment_method"))
                    customer_id = _stripe_id(obj.get("customer"))
            elif obj.get("object") == "payment_intent":
                if obj.get("setup_future_usage"):
                    payment_method_id = _stripe_id(obj.get("payment_method"))
                    customer_id = _stripe_id(obj.get("customer"))

            if not payment_method_id or not customer_id:
                return None

            pm = stripe.PaymentMethod.retrieve(payment_method_id)
            card = pm.get("card") or {}
            return TokenizeCardResult(
                token=payment_method_id,
                customer_code=customer_id,
                brand=card.get("brand", ""),
                last4=card.get("last4", ""),
                exp_month=str(card.get("exp_month", "")),
                exp_year=str(card.get("exp_year", "")),
                signature=card.get("fingerprint", ""),
                reusable=True,
                card_type=card.get("funding", ""),
                currency="",
            )
        except stripe.StripeError:
            return None

    def charge_card_token(
        self,
        token: str,
        customer_code: str,
        email: str,
        amount: Decimal,
        tx_ref: str,
        currency: str = "USD",
        subunit_multiplier: int = 100,
    ) -> ChargeTokenResult:
        try:
            pi = stripe.PaymentIntent.create(
                amount=int(amount * subunit_multiplier),
                currency=currency.lower(),
                customer=customer_code,
                payment_method=token,
                off_session=True,
                confirm=True,
                metadata={"tx_ref": tx_ref},
            )
            return ChargeTokenResult(
                is_successful=pi.status == "succeeded",
                gateway_reference=pi.id,
                raw_response=pi,
            )
        except stripe.CardError as e:
            raise ValidationError(f"Card charge declined: {e.user_message or str(e)}")
        except stripe.StripeError as e:
            raise ValidationError(f"Card charge failed: {str(e)}")

    # --- Stripe Connect (withdrawal destinations) -------------------------

    def create_connect_account(self, email: str) -> str:
        """Create an Express connected account for payouts."""
        try:
            account = stripe.Account.create(
                type="express",
                email=email,
                capabilities={"transfers": {"requested": True}},
            )
            return account.id
        except stripe.StripeError as e:
            raise ValidationError(f"Could not create Stripe payout account: {str(e)}")

    def create_onboarding_link(
        self, account_id: str, refresh_url: str, return_url: str
    ) -> str:
        """Return a Stripe-hosted onboarding URL where the user attaches a
        bank account or debit card. Links are single-use and short-lived."""
        try:
            link = stripe.AccountLink.create(
                account=account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )
            return link.url
        except stripe.StripeError as e:
            raise ValidationError(f"Could not create Stripe onboarding link: {str(e)}")

    def get_connect_account_status(self, account_id: str) -> dict:
        try:
            account = stripe.Account.retrieve(account_id)
            requirements = account.get("requirements") or {}
            return {
                "payouts_enabled": bool(account.get("payouts_enabled")),
                "details_submitted": bool(account.get("details_submitted")),
                "currently_due": requirements.get("currently_due") or [],
            }
        except stripe.StripeError as e:
            raise ValidationError(f"Could not fetch Stripe account status: {str(e)}")

    def initiate_connect_payout(
        self,
        account_id: str,
        amount: Decimal,
        currency: str,
        reference: str,
    ) -> InitiateTransferResult:
        """Transfer funds to a connected account. Stripe then automatically
        pays out to whatever destination (bank/debit card) the user attached."""
        try:
            transfer = stripe.Transfer.create(
                amount=int(amount * 100),
                currency=currency.lower(),
                destination=account_id,
                transfer_group=reference,
                metadata={"reference": reference},
            )
            return InitiateTransferResult(
                transfer_reference=transfer.id,
                status="success",
                raw_response=transfer,
            )
        except stripe.StripeError as e:
            raise ValidationError(f"Stripe payout failed: {str(e)}")

    def resolve_bank_account(
        self, account_number: str, bank_code: str
    ) -> ResolveAccountResult:
        raise NotImplementedError(
            "Bank account resolution is not supported"
            "by Stripe directly without Connect integration."
        )

    def initiate_transfer(
        self,
        account_number: str,
        bank_code: str,
        amount: Decimal,
        narration: str,
        reference: str,
        currency: str = "USD",
    ) -> InitiateTransferResult:
        raise NotImplementedError(
            "Direct transfers are not fully supported without Stripe Connect setup."
        )

    def get_banks(self, country: str = "US") -> list[dict]:
        return []

    def verify_webhook_signature(self, raw_body: bytes, headers, payload: dict) -> bool:
        signature = headers.get("Stripe-Signature")
        if not signature or not self.webhook_secret:
            return False

        try:
            stripe.Webhook.construct_event(
                payload=raw_body, sig_header=signature, secret=self.webhook_secret
            )
            return True
        except ValueError:
            # Invalid payload
            return False
        except stripe.error.SignatureVerificationError:
            # Invalid signature
            return False

    def parse_webhook_payload(self, payload: dict) -> WebhookPaymentData:
        event_type = payload.get("type", "")
        obj = payload.get("data", {}).get("object", {})

        if event_type == "checkout.session.completed":
            # client_reference_id is set to our tx_ref when the session was created
            tx_ref = obj.get("client_reference_id", "")
            gateway_reference = obj.get("id", "")  # cs_... session id
            payment_status = obj.get("payment_status", "")
            # "no_payment_required" covers setup-mode sessions (card save)
            is_successful = payment_status in ("paid", "no_payment_required")
            # amount_total is null for setup-mode sessions (no charge)
            raw_amount = Decimal(str(obj.get("amount_total") or 0))
            amount_paid = (raw_amount / 100).quantize(Decimal("0.01"))
            currency = (obj.get("currency") or "").upper()
        elif event_type == "setup_intent.succeeded":
            tx_ref = (obj.get("metadata") or {}).get("tx_ref", "")
            gateway_reference = obj.get("id", "")  # seti_...
            is_successful = obj.get("status", "") == "succeeded"
            amount_paid = Decimal("0.00")
            currency = ""
        elif event_type == "payment_intent.succeeded":
            # metadata.tx_ref is set when creating the PaymentIntent
            tx_ref = (obj.get("metadata") or {}).get("tx_ref", "")
            gateway_reference = obj.get("id", "")  # pi_...
            is_successful = obj.get("status", "") == "succeeded"
            raw_amount = Decimal(str(obj.get("amount_received", "0")))
            amount_paid = (raw_amount / 100).quantize(Decimal("0.01"))
            currency = (obj.get("currency") or "").upper()
        else:
            # Unsupported event type — treat as not successful
            return WebhookPaymentData(
                is_successful=False,
                amount_paid=Decimal("0"),
                tx_ref="",
                gateway_reference="",
                currency="",
            )

        return WebhookPaymentData(
            is_successful=is_successful,
            amount_paid=amount_paid,
            tx_ref=tx_ref,
            gateway_reference=gateway_reference,
            currency=currency,
        )
