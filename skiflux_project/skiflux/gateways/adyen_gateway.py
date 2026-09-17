from decimal import Decimal
from typing import Optional

import Adyen
from django.conf import settings
from rest_framework.exceptions import ValidationError

from .base import (
    InitiatePaymentResult,
    InitiateTransferResult,
    PaymentGateway,
    ResolveAccountResult,
    VerifyPaymentResult,
    WebhookPaymentData,
)


class AdyenGateway(PaymentGateway):
    def __init__(self):
        self.api_key = getattr(settings, "ADYEN_API_KEY", "")
        self.merchant_account = getattr(settings, "ADYEN_MERCHANT_ACCOUNT", "")
        self.environment = getattr(settings, "ADYEN_ENVIRONMENT", "test")
        self.webhook_secret = getattr(settings, "ADYEN_WEBHOOK_SECRET", "")

        self.adyen = Adyen.Adyen()
        self.adyen.client.xapikey = self.api_key
        self.adyen.client.platform = self.environment
        self.adyen.client.merchant_account = self.merchant_account

    @property
    def name(self) -> str:
        return "adyen"

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
        amount_minor_units = int(amount * subunit_multiplier)

        request_data = {
            "reference": tx_ref,
            "amount": {"value": amount_minor_units, "currency": currency},
            "merchantAccount": self.merchant_account,
            "returnUrl": redirect_url,
            "shopperEmail": email,
        }

        try:
            # Generate a Payment Link
            result = self.adyen.checkout.payment_links(request_data)

            return InitiatePaymentResult(
                gateway_reference=result.message.get("id"),
                checkout_url=result.message.get("url"),
                raw_response=result.message,
            )
        except Exception as e:
            raise ValidationError(f"Adyen payment initiation failed: {str(e)}")

    def verify_payment(self, gateway_reference: str) -> VerifyPaymentResult:
        try:
            result = self.adyen.checkout.payment_links_api.get_payment_link(
                gateway_reference
            )
            status = result.message.get("status")

            is_successful = status == "completed"

            amount_dict = result.message.get("amount", {})
            currency = amount_dict.get("currency", "USD")
            value = amount_dict.get("value", 0)
            amount_paid = Decimal(value) / 100

            return VerifyPaymentResult(
                is_successful=is_successful,
                amount_paid=amount_paid,
                currency=currency,
                gateway_reference=gateway_reference,
                raw_response=result.message,
            )
        except Exception as e:
            raise ValidationError(f"Adyen verification failed: {str(e)}")

    def resolve_bank_account(
        self, account_number: str, bank_code: str
    ) -> ResolveAccountResult:
        raise NotImplementedError(
            "Bank account resolution is not supported directly by Adyen."
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
            "Direct transfers are not supported without Adyen Balance Platform setup."
        )

    def get_banks(self, country: str = "US") -> list[dict]:
        return []

    def verify_webhook_signature(self, raw_body: bytes, headers, payload: dict) -> bool:
        if not self.webhook_secret:
            return False

        hmac_validator = Adyen.util.HmacValidator()
        try:
            notification_item = payload.get("notificationItems", [])[0].get(
                "NotificationRequestItem"
            )
            return hmac_validator.verify_signature(
                self.webhook_secret, notification_item
            )
        except Exception:
            return False

    def parse_webhook_payload(self, payload: dict) -> WebhookPaymentData:
        """Parse an Adyen AUTHORISATION notification."""
        try:
            item = payload.get("notificationItems", [])[0].get(
                "NotificationRequestItem", {}
            )
        except (IndexError, AttributeError, KeyError):
            return WebhookPaymentData(
                is_successful=False,
                amount_paid=Decimal("0"),
                tx_ref="",
                gateway_reference="",
                currency="",
            )

        event_code = item.get("eventCode", "")
        success = str(item.get("success", "false")).lower() == "true"
        is_successful = event_code == "AUTHORISATION" and success

        # merchantReference is our internal tx_ref
        tx_ref = item.get("merchantReference", "")
        # pspReference is Adyen's transaction reference
        gateway_reference = item.get("pspReference", "")

        amount_dict = item.get("amount", {})
        currency = amount_dict.get("currency", "")
        # Adyen sends amounts in minor units (cents, kobo, etc.)
        raw_value = Decimal(str(amount_dict.get("value", "0")))
        amount_paid = (raw_value / 100).quantize(Decimal("0.01"))

        return WebhookPaymentData(
            is_successful=is_successful,
            amount_paid=amount_paid,
            tx_ref=tx_ref,
            gateway_reference=gateway_reference,
            currency=currency,
        )
