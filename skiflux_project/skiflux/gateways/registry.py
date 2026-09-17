from typing import List, Tuple

from skiflux.gateways.adyen_gateway import AdyenGateway
from skiflux.gateways.flutterwave import FlutterwaveGateway
from skiflux.gateways.paystack import PaystackGateway
from skiflux.gateways.stripe_gateway import StripeGateway
from skiflux.models.wallet import SystemFinancialConfig

from .base import PaymentGateway


class PaymentGatewayFactory:
    _gateways = {
        "flutterwave": FlutterwaveGateway,
        "paystack": PaystackGateway,
        "stripe": StripeGateway,
        "adyen": AdyenGateway,
    }

    @classmethod
    def get_gateway(cls, name: str = None, *, purpose: str = "topup"):
        config = SystemFinancialConfig.get_config()
        if purpose == "withdrawal":
            enabled = config.enabled_withdrawal_gateways
        else:
            enabled = config.enabled_topup_gateways

        if not enabled:
            raise ValueError(
                f"No payment gateways are currently enabled for {purpose}."
            )
        if not name:
            name = enabled[0]
        if name not in enabled:
            raise ValueError(
                f"Gateway '{name}' is disabled or unsupported for {purpose}."
            )
        gateway_class = cls._gateways.get(name.lower())
        if not gateway_class:
            raise ValueError(f"Gateway '{name}' implementation not found.")

        return gateway_class()


def get_enabled_topup_gateways() -> List[Tuple[str, PaymentGateway]]:
    """Returns list of (name, gateway) tuples enabled for top-up."""
    config = SystemFinancialConfig.get_config()
    gateways = []
    for name in config.enabled_topup_gateways:
        try:
            gateways.append(
                (name, PaymentGatewayFactory.get_gateway(name, purpose="topup"))
            )
        except ValueError:
            pass
    return gateways


def get_enabled_withdrawal_gateways() -> List[Tuple[str, PaymentGateway]]:
    config = SystemFinancialConfig.get_config()
    gateways = []
    for name in config.enabled_withdrawal_gateways:
        try:
            gateways.append(
                (name, PaymentGatewayFactory.get_gateway(name, purpose="withdrawal"))
            )
        except ValueError:
            pass
    return gateways
