import hashlib
import hmac
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError

from .base import (
    ChargeTokenResult,
    InitiatePaymentResult,
    InitiateTransferResult,
    PaymentGateway,
    RefundResult,
    ResolveAccountResult,
    TokenizeCardResult,
    VerifyPaymentResult,
    WebhookPaymentData,
)
from .payment_channels import paystack_channels


class PaystackGateway(PaymentGateway):
    def __init__(self):
        self.secret_key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        self.base_url = "https://api.paystack.co"
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    @property
    def name(self) -> str:
        return "paystack"

    def initiate_payment(
        self,
        amount: Decimal,
        email: str,
        tx_ref: str,
        currency: str = "NGN",
        redirect_url: Optional[str] = None,
        subunit_multiplier: int = 100,
        save_card: bool = False,
        payment_method: str = "all",
    ) -> InitiatePaymentResult:
        # Paystack returns a reusable authorization on any successful card
        # charge, so no special session parameters are needed for save_card.
        if not redirect_url:
            redirect_url = getattr(settings, "PAYMENT_REDIRECT_URL", "")

        # Convert to smallest currency unit (e.g. kobo for NGN, cents for USD)
        amount_smallest_unit = int(amount * subunit_multiplier)

        payload = {
            "reference": tx_ref,
            "amount": amount_smallest_unit,
            "currency": currency,
            "email": email,
            "callback_url": redirect_url,
            "metadata": {
                "custom_fields": [
                    {
                        "display_name": "Purpose",
                        "variable_name": "purpose",
                        "value": "SkillFlux Wallet Top-up",
                    }
                ]
            },
        }
        channels = paystack_channels(payment_method)
        if channels:
            payload["channels"] = channels

        try:
            response = requests.post(
                f"{self.base_url}/transaction/initialize",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status"):
                return InitiatePaymentResult(
                    gateway_reference=data["data"].get("reference", tx_ref),
                    checkout_url=data["data"]["authorization_url"],
                    raw_response=data,
                )
            raise ValidationError(data.get("message", "Payment initiation failed"))
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    err_data = e.response.json()
                    raise ValidationError(
                        err_data.get("message", "Payment initiation failed")
                    )
                except ValueError:
                    raise ValidationError(
                        f"Payment initiation failed with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

    def verify_payment(self, gateway_reference: str) -> VerifyPaymentResult:
        try:
            response = requests.get(
                f"{self.base_url}/transaction/verify/{gateway_reference}",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            tx_data = data.get("data", {})
            is_successful = data.get("status") and tx_data.get("status") == "success"

            return VerifyPaymentResult(
                is_successful=is_successful,
                amount_paid=Decimal(str(tx_data.get("amount", 0))) / 100,
                currency=tx_data.get("currency", "NGN"),
                gateway_reference=str(tx_data.get("reference")),
                raw_response=data,
            )
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    err_data = e.response.json()
                    raise ValidationError(
                        err_data.get("message", "Verification failed")
                    )
                except ValueError:
                    raise ValidationError(
                        f"Verification failed with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

    def refund_payment(
        self,
        transaction_reference: str,
        amount: Decimal,
        currency: str = "NGN",
        subunit_multiplier: int = 100,
        customer_note: str = "",
        merchant_note: str = "",
    ) -> RefundResult:
        payload = {
            "transaction": transaction_reference,
            "amount": int(amount * subunit_multiplier),
            "currency": currency,
        }
        if customer_note:
            payload["customer_note"] = customer_note
        if merchant_note:
            payload["merchant_note"] = merchant_note

        try:
            response = requests.post(
                f"{self.base_url}/refund",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            refund_data = data.get("data", {})
            is_successful = bool(data.get("status"))
            return RefundResult(
                is_successful=is_successful,
                refund_reference=str(refund_data.get("id", "")),
                raw_response=data,
            )
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    err_data = e.response.json()
                    raise ValidationError(err_data.get("message", "Refund failed"))
                except ValueError:
                    raise ValidationError(
                        f"Refund failed with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

    def extract_card_authorization(self, raw_response: dict):
        """Extract a reusable card authorization from a Paystack verify or
        webhook payload (both nest the transaction under ``data``)."""
        data = raw_response.get("data", raw_response) or {}
        auth = data.get("authorization") or {}
        if not auth or auth.get("channel") != "card":
            return None
        if not auth.get("reusable"):
            return None
        token = auth.get("authorization_code", "")
        if not token:
            return None
        customer = data.get("customer") or {}
        return TokenizeCardResult(
            token=token,
            customer_code=customer.get("customer_code", ""),
            brand=(auth.get("brand") or "").strip(),
            last4=auth.get("last4", ""),
            exp_month=str(auth.get("exp_month", "")),
            exp_year=str(auth.get("exp_year", "")),
            signature=auth.get("signature", ""),
            reusable=True,
            bank_name=auth.get("bank") or "",
            card_type=(auth.get("card_type") or "").strip(),
            currency=data.get("currency", ""),
        )

    def charge_card_token(
        self,
        token: str,
        customer_code: str,
        email: str,
        amount: Decimal,
        tx_ref: str,
        currency: str = "NGN",
        subunit_multiplier: int = 100,
    ) -> ChargeTokenResult:
        payload = {
            "authorization_code": token,
            "email": email,
            "amount": int(amount * subunit_multiplier),
            "currency": currency,
            "reference": tx_ref,
        }
        try:
            response = requests.post(
                f"{self.base_url}/transaction/charge_authorization",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            tx_data = data.get("data", {})
            is_successful = bool(
                data.get("status") and tx_data.get("status") == "success"
            )
            return ChargeTokenResult(
                is_successful=is_successful,
                gateway_reference=str(tx_data.get("reference", tx_ref)),
                raw_response=data,
            )
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    err_data = e.response.json()
                    raise ValidationError(err_data.get("message", "Card charge failed"))
                except ValueError:
                    raise ValidationError(
                        f"Card charge failed with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

    def resolve_bank_account(
        self, account_number: str, bank_code: str
    ) -> ResolveAccountResult:
        try:
            response = requests.get(
                f"{self.base_url}/bank/resolve?account_number={account_number}&bank_code={bank_code}",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status"):
                acct_data = data.get("data", {})
                return ResolveAccountResult(
                    account_name=acct_data.get("account_name"),
                    account_number=acct_data.get("account_number"),
                    raw_response=data,
                )
            raise ValidationError(data.get("message", "Account resolution failed"))
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    err_data = e.response.json()
                    raise ValidationError(
                        err_data.get("message", "Account resolution failed")
                    )
                except ValueError:
                    raise ValidationError(
                        f"Account resolution failed with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

    def initiate_transfer(
        self,
        account_number: str,
        bank_code: str,
        amount: Decimal,
        narration: str,
        reference: str,
        currency: str = "NGN",
    ) -> InitiateTransferResult:
        # First create a transfer recipient
        recipient_payload = {
            "type": "nuban",
            "name": "SkillFlux User",
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        }

        try:
            resp_recip = requests.post(
                f"{self.base_url}/transferrecipient",
                json=recipient_payload,
                headers=self.headers,
            )
            resp_recip.raise_for_status()
            recip_data = resp_recip.json()
            if not recip_data.get("status"):
                raise ValidationError(
                    recip_data.get("message", "Failed to create transfer recipient")
                )

            recipient_code = recip_data["data"]["recipient_code"]
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    raise ValidationError(
                        e.response.json().get(
                            "message",
                            "Transfer initiation failed at recipient creation",
                        )
                    )
                except ValueError:
                    raise ValidationError(
                        f"Transfer initiation failed at recipient creation with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

        # Now initiate the transfer
        amount_smallest_unit = int(amount * 100)
        transfer_payload = {
            "source": "balance",
            "amount": amount_smallest_unit,
            "reference": reference,
            "recipient": recipient_code,
            "reason": narration,
        }

        try:
            response = requests.post(
                f"{self.base_url}/transfer", json=transfer_payload, headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status"):
                tx_data = data.get("data", {})
                return InitiateTransferResult(
                    transfer_reference=str(
                        tx_data.get("transfer_code", tx_data.get("reference"))
                    ),
                    status=tx_data.get("status"),
                    raw_response=data,
                )
            raise ValidationError(data.get("message", "Transfer initiation failed"))
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    err_data = e.response.json()
                    raise ValidationError(
                        err_data.get("message", "Transfer initiation failed")
                    )
                except ValueError:
                    raise ValidationError(
                        f"Transfer initiation failed with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

    def get_banks(self, country: str = "nigeria") -> list[dict]:
        try:
            # Paystack expects country name or currency
            response = requests.get(
                f"{self.base_url}/bank?country={country}", headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status"):
                return data.get("data", [])
            raise ValidationError(
                data.get("message", "Failed to fetch banks from gateway")
            )
        except requests.RequestException as e:
            if e.response is not None:
                try:
                    err_data = e.response.json()
                    raise ValidationError(
                        err_data.get("message", "Failed to fetch banks from gateway")
                    )
                except ValueError:
                    raise ValidationError(
                        f"Failed to fetch banks from gateway with status {e.response.status_code}: {e.response.text}"  # noqa: E501
                    )
            raise ValidationError("Could not connect to payment gateway")

    def verify_webhook_signature(self, raw_body: bytes, headers, payload: dict) -> bool:
        signature = headers.get("x-paystack-signature")
        if not signature or not self.secret_key:
            return False

        # Paystack webhook payload must be hashed with secret key
        hash = hmac.new(
            self.secret_key.encode("utf-8"), raw_body, hashlib.sha512
        ).hexdigest()
        return hash == signature

    def parse_webhook_payload(self, payload: dict) -> WebhookPaymentData:
        """Parse a Paystack charge.success webhook payload."""
        data = payload.get("data", {})
        status = data.get("status", "").lower()
        # Paystack uses `reference` as both the internal tx_ref and gateway_reference
        tx_ref = data.get("reference", "")
        gateway_reference = str(data.get("id", tx_ref))
        # Paystack sends amounts in smallest unit (kobo = 1/100 of NGN)
        raw_amount = Decimal(str(data.get("amount", "0")))
        amount_paid = (raw_amount / 100).quantize(Decimal("0.01"))
        currency = data.get("currency", "")
        return WebhookPaymentData(
            is_successful=(status == "success"),
            amount_paid=amount_paid,
            tx_ref=tx_ref,
            gateway_reference=gateway_reference,
            currency=currency,
        )
