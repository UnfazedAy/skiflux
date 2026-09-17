from decimal import Decimal
from typing import Optional

import requests
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
from .payment_channels import flutterwave_payment_options


class FlutterwaveGateway(PaymentGateway):
    def __init__(self):
        self.secret_key = getattr(settings, "FLUTTERWAVE_SECRET_KEY", "")
        self.base_url = getattr(
            settings, "FLUTTERWAVE_BASE_URL", "https://api.flutterwave.com"
        ).rstrip("/")
        self.webhook_secret = getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", "")
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    @property
    def name(self) -> str:
        return "flutterwave"

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
        if not redirect_url:
            redirect_url = getattr(settings, "PAYMENT_REDIRECT_URL", "")

        # Flutterwave accepts amounts in major currency units (not smallest unit)
        payload = {
            "tx_ref": tx_ref,
            "amount": str(amount),
            "currency": currency,
            "redirect_url": redirect_url,
            "customer": {"email": email},
            "customizations": {
                "title": "SkillFlux Wallet Top-up",
                "description": "Fund your SkillFlux wallet.",
            },
        }
        payment_options = flutterwave_payment_options(payment_method)
        if payment_options:
            payload["payment_options"] = payment_options

        try:
            response = requests.post(
                f"{self.base_url}/v3/payments", json=payload, headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success":
                gw_ref = data["data"].get("id")
                return InitiatePaymentResult(
                    gateway_reference=str(gw_ref) if gw_ref else None,
                    checkout_url=data["data"]["link"],
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
                f"{self.base_url}/v3/transactions/{gateway_reference}/verify",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            tx_data = data.get("data", {})
            is_successful = (
                data.get("status") == "success"
                and tx_data.get("status") == "successful"
            )

            return VerifyPaymentResult(
                is_successful=is_successful,
                amount_paid=Decimal(str(tx_data.get("amount", "0"))),
                currency=tx_data.get("currency", "NGN"),
                gateway_reference=str(tx_data.get("id")),
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

    def resolve_bank_account(
        self, account_number: str, bank_code: str
    ) -> ResolveAccountResult:
        payload = {"account_number": account_number, "account_bank": bank_code}
        try:
            response = requests.post(
                f"{self.base_url}/v3/accounts/resolve",
                json=payload,
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success":
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
        payload = {
            "account_bank": bank_code,
            "account_number": account_number,
            "amount": str(amount),
            "narration": narration,
            "currency": currency,
            "reference": reference,
        }
        try:
            response = requests.post(
                f"{self.base_url}/v3/transfers", json=payload, headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success":
                tx_data = data.get("data", {})
                return InitiateTransferResult(
                    transfer_reference=str(tx_data.get("id")),
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

    def get_banks(self, country: str = "NG") -> list[dict]:
        try:
            response = requests.get(
                f"{self.base_url}/v3/banks/{country}", headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success":
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
        signature = headers.get("verif-hash")
        if not signature or not self.webhook_secret:
            return False
        return signature == self.webhook_secret

    def parse_webhook_payload(self, payload: dict) -> WebhookPaymentData:
        """Parse a Flutterwave charge.completed webhook payload."""
        data = payload.get("data", {})
        status = data.get("status", "").lower()
        tx_ref = data.get("tx_ref", "")
        gateway_reference = str(data.get("id", ""))
        # Flutterwave sends amounts in major currency units (no conversion needed)
        amount_paid = Decimal(str(data.get("amount", "0")))
        currency = data.get("currency", "")
        return WebhookPaymentData(
            is_successful=(status == "successful"),
            amount_paid=amount_paid,
            tx_ref=tx_ref,
            gateway_reference=gateway_reference,
            currency=currency,
        )
