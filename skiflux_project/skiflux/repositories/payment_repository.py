from datetime import timedelta
from typing import Optional
from django.utils import timezone
from skiflux.models.wallet import PaymentTransaction
from skiflux.models import CurrencyConfig, TransactionStatusEvent


class PaymentTransactionRepository:
    def get_by_tx_ref(
        self, tx_ref: str, lock: bool = False
    ) -> Optional[PaymentTransaction]:
        qs = PaymentTransaction.objects.all()
        if lock:
            qs = qs.select_for_update()
        return qs.filter(tx_ref=tx_ref).first()

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> Optional[PaymentTransaction]:
        return PaymentTransaction.objects.filter(
            idempotency_key=idempotency_key
        ).first()

    def find_pending_duplicate(
        self,
        owner,
        amount_fiat,
        currency: str,
        gateway: str,
        within_minutes: int = 30,
    ) -> Optional[PaymentTransaction]:
        """Return the most recent INITIATED/PENDING transaction that matches
        the same owner (User or AdminUser), amount, currency, and gateway
        within the given time window. Used to prevent duplicate checkout
        sessions being created."""
        from skiflux.models import User

        owner_filter = (
            {"user": owner} if isinstance(owner, User) else {"admin_user": owner}
        )
        cutoff = timezone.now() - timedelta(minutes=within_minutes)
        return (
            PaymentTransaction.objects.filter(
                amount_fiat=amount_fiat,
                currency=currency,
                gateway=gateway,
                status__in=[
                    PaymentTransaction.Status.INITIATED,
                    PaymentTransaction.Status.PENDING,
                ],
                created_at__gte=cutoff,
                **owner_filter,
            )
            .order_by("-created_at")
            .first()
        )

    def create(self, **kwargs) -> PaymentTransaction:
        return PaymentTransaction.objects.create(**kwargs)

    def update(self, payment_tx: PaymentTransaction, update_fields: list) -> None:
        payment_tx.save(update_fields=update_fields)

    def get_currency_config(self, currency_code: str):
        return CurrencyConfig.objects.get(currency_code=currency_code, is_active=True)

    def create_status_event(self, **kwargs):
        return TransactionStatusEvent.objects.create(**kwargs)

    def update_or_create_currency(self, currency_code: str, defaults: dict):
        return CurrencyConfig.objects.update_or_create(
            currency_code=currency_code, defaults=defaults
        )

    def get_all_currencies(self):
        return list(CurrencyConfig.objects.all())
