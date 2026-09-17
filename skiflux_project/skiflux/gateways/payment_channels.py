"""Map UI payment_method values to gateway-specific channel filters."""

from typing import Optional

TOPUP_PAYMENT_METHOD_ALL = "all"
TOPUP_PAYMENT_METHOD_CARD = "card"
TOPUP_PAYMENT_METHOD_BANK_TRANSFER = "bank_transfer"

TOPUP_PAYMENT_METHOD_CHOICES = [
    TOPUP_PAYMENT_METHOD_ALL,
    TOPUP_PAYMENT_METHOD_CARD,
    TOPUP_PAYMENT_METHOD_BANK_TRANSFER,
]


def paystack_channels(payment_method: str) -> Optional[list[str]]:
    if payment_method == TOPUP_PAYMENT_METHOD_CARD:
        return ["card"]
    if payment_method == TOPUP_PAYMENT_METHOD_BANK_TRANSFER:
        return ["bank_transfer"]
    return None


def flutterwave_payment_options(payment_method: str) -> Optional[str]:
    if payment_method == TOPUP_PAYMENT_METHOD_CARD:
        return "card"
    if payment_method == TOPUP_PAYMENT_METHOD_BANK_TRANSFER:
        return "banktransfer"
    return None
