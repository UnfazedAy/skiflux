from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler

from skiflux.utils.responses import APIResponse


class SkifluxDomainError(ValidationError):
    """Base class for all domain-specific exceptions."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(detail=message)
        self.message = message
        self.status_code = status_code


class WalletLockedError(SkifluxDomainError):
    def __init__(
        self, message="Transaction rejected. Wallet is currently suspended/locked."
    ):
        super().__init__(message, status_code=403)


class InsufficientFundsError(SkifluxDomainError):
    def __init__(self, message="Insufficient Skillcoin balance."):
        super().__init__(message, status_code=400)


class PaymentVerificationError(SkifluxDomainError):
    def __init__(self, message="Payment verification failed."):
        super().__init__(message, status_code=400)


def skiflux_exception_handler(exc, context):
    if isinstance(exc, SkifluxDomainError):
        return APIResponse(
            status="error",
            status_code=exc.status_code,
            message=exc.message,
        )

    response = exception_handler(exc, context)

    if response is not None:
        if isinstance(response.data, dict) and "detail" in response.data:
            return APIResponse(
                status="error",
                status_code=response.status_code,
                message=str(response.data["detail"]),
            )

        return APIResponse(
            status="error",
            status_code=response.status_code,
            message=response.data,
        )

    return None
