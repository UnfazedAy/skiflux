from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from skiflux.models.wallet import GatewayFeeConfig


@dataclass
class InitiatePaymentResult:
    gateway_reference: Optional[str]
    checkout_url: str
    raw_response: dict


@dataclass
class VerifyPaymentResult:
    is_successful: bool
    amount_paid: Decimal
    currency: str
    gateway_reference: str
    raw_response: dict


@dataclass
class ResolveAccountResult:
    account_name: str
    account_number: str
    raw_response: dict


@dataclass
class InitiateTransferResult:
    transfer_reference: str
    status: str
    raw_response: dict


@dataclass
class WebhookPaymentData:
    """Normalised payment data parsed from a gateway webhook payload."""

    is_successful: bool
    amount_paid: Decimal
    tx_ref: str
    gateway_reference: str
    currency: str = ""


@dataclass
class TokenizeCardResult:
    """A reusable card token extracted from a successful gateway payment."""

    token: str
    customer_code: str
    brand: str
    last4: str
    exp_month: str
    exp_year: str
    signature: str
    reusable: bool
    bank_name: str = ""
    card_type: str = ""
    currency: str = ""


@dataclass
class ChargeTokenResult:
    """Result of charging a previously saved card token."""

    is_successful: bool
    gateway_reference: str
    raw_response: dict


@dataclass
class RefundResult:
    """Result of refunding a prior successful charge."""

    is_successful: bool
    refund_reference: str
    raw_response: dict


class PaymentGateway(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the gateway (e.g., 'flutterwave', 'paystack')."""
        pass

    @abstractmethod
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
        """Initiate a payment session with the gateway.

        Args:
            amount: The fiat amount in major currency units (e.g. 500 for $500).
            email: Customer email.
            tx_ref: Internal transaction reference.
            currency: ISO 4217 currency code.
            redirect_url: URL to redirect to after payment.
            subunit_multiplier: How many smallest units make up 1 major unit.
                Use 100 for USD/NGN/GBP/EUR (2 decimal places, default).
                Use 1000 for KWD/BHD (3 decimal places).
                Use 1 for JPY/KRW (0 decimal places).
            payment_method: Restrict hosted checkout to ``card``,
                ``bank_transfer``, or ``all`` (gateway default).
        """
        pass

    @abstractmethod
    def verify_payment(self, gateway_reference: str) -> VerifyPaymentResult:
        pass

    def calculate_fee(
        self,
        amount: Decimal,
        currency: str = "NGN",
    ) -> Decimal:
        """Calculate the gateway's processing fee using database configuration."""
        # Normalise to uppercase so 'usd' and 'USD' both hit the same row
        currency = currency.upper()

        # 1. Try to get the specific currency config
        config = GatewayFeeConfig.objects.filter(
            gateway_name=self.name, currency_code=currency
        ).first()

        # 2. Fall back to 'ALL'
        if not config:
            config = GatewayFeeConfig.objects.filter(
                gateway_name=self.name, currency_code="ALL"
            ).first()

        # 3. If no config is found at all, assume 0 fee
        if not config:
            return Decimal("0.00")

        fee = Decimal("0.00")

        # Percentage
        if config.fee_percentage > Decimal("0.00"):
            fee += (amount * config.fee_percentage / Decimal("100.00")).quantize(
                Decimal("0.01")
            )

        # Flat fee
        if config.flat_fee > Decimal("0.00") and amount >= config.flat_fee_threshold:
            fee += config.flat_fee

        # VAT
        vat = Decimal("0.00")
        if config.vat_percentage > Decimal("0.00"):
            vat += (fee * config.vat_percentage / Decimal("100.00")).quantize(
                Decimal("0.01")
            )
        if config.vat_flat > Decimal("0.00"):
            vat += config.vat_flat

        total_fee = fee + vat

        # Cap
        if config.cap_amount is not None and total_fee > config.cap_amount:
            total_fee = config.cap_amount

        return total_fee

    # --- Saved card (tokenization) capabilities -------------------------
    # Optional per gateway; safe defaults keep gateways without card
    # support working unchanged.

    def extract_card_authorization(
        self, raw_response: dict
    ) -> Optional[TokenizeCardResult]:
        """Parse a verify/webhook payload for a reusable card token.

        Returns None when the gateway does not support tokenization or the
        payload does not contain a reusable card authorization.
        """
        return None

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
        """Charge a previously saved card token (one-tap top-up)."""
        raise NotImplementedError(
            f"Saved-card charges are not supported on {self.name}."
        )

    def refund_payment(
        self,
        transaction_reference: str,
        amount: Decimal,
        currency: str = "NGN",
        subunit_multiplier: int = 100,
        customer_note: str = "",
        merchant_note: str = "",
    ) -> RefundResult:
        """Refund a prior successful charge back to the customer."""
        raise NotImplementedError(f"Refunds are not supported on {self.name}.")

    @abstractmethod
    def resolve_bank_account(
        self, account_number: str, bank_code: str
    ) -> ResolveAccountResult:
        pass

    @abstractmethod
    def initiate_transfer(
        self,
        account_number: str,
        bank_code: str,
        amount: Decimal,
        narration: str,
        reference: str,
        currency: str = "NGN",
    ) -> InitiateTransferResult:
        pass

    @abstractmethod
    def get_banks(self, country: str = "NG") -> list[dict]:
        pass

    @abstractmethod
    def verify_webhook_signature(self, raw_body: bytes, headers, payload: dict) -> bool:
        pass

    @abstractmethod
    def parse_webhook_payload(self, payload: dict) -> WebhookPaymentData:
        """Parse a raw inbound webhook payload into a normalised WebhookPaymentData.

        This is called by `PaymentService.handle_webhook` to extract the
        payment outcome directly from the webhook body — avoiding a second
        round-trip verification call to the gateway API.

        Returns:
            WebhookPaymentData with at minimum is_successful, amount_paid,
            tx_ref, and gateway_reference filled in.

        Raises:
            ValidationError if the payload cannot be parsed.
        """
        pass
