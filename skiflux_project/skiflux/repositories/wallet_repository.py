from decimal import Decimal
from typing import Optional, Tuple
from uuid import UUID

from django.db.models import Case, DecimalField, Sum, When

from skiflux.models.status_events import TransactionStatusEvent
from skiflux.models.wallet import SkillcoinTransaction, UserWallet, WithdrawalHold


class WalletRepository:
    def get_wallet(
        self, owner_kwargs: dict, lock: bool = False
    ) -> Optional[UserWallet]:
        qs = UserWallet.objects.all()
        if lock:
            qs = qs.select_for_update()
        return qs.filter(**owner_kwargs).first()

    def get_or_create_wallet(
        self, owner_kwargs: dict, lock: bool = False
    ) -> Tuple[UserWallet, bool]:
        qs = UserWallet.objects.all()
        if lock:
            qs = qs.select_for_update()
        return qs.get_or_create(**owner_kwargs)

    def get_platform_wallet(self, lock: bool = False) -> Tuple[UserWallet, bool]:
        qs = UserWallet.objects.all()
        if lock:
            qs = qs.select_for_update()
        return qs.get_or_create(
            is_platform_wallet=True, defaults={"user": None, "admin_user": None}
        )

    def get_posted_ledger_sum(self, wallet: UserWallet) -> Decimal:
        total = SkillcoinTransaction.objects.filter(
            wallet=wallet,
            status__in=SkillcoinTransaction.BALANCE_STATUSES,
        ).aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0.00")

    def create_transaction(self, **kwargs) -> Tuple[SkillcoinTransaction, bool]:
        idempotency_key = kwargs.get("idempotency_key")
        if idempotency_key:
            existing = SkillcoinTransaction.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                return existing, False

        tx = SkillcoinTransaction.objects.create(**kwargs)
        return tx, True

    def create_status_event(self, **kwargs):
        return TransactionStatusEvent.objects.create(**kwargs)

    def get_active_holds_total(self, wallet: UserWallet) -> Decimal:
        total = WithdrawalHold.objects.filter(
            wallet=wallet, status=WithdrawalHold.Status.ACTIVE
        ).aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0.00")

    def get_wallet_by_pk(self, pk, lock: bool = False) -> Optional[UserWallet]:
        qs = UserWallet.objects.all()
        if lock:
            qs = qs.select_for_update()
        return qs.filter(pk=pk).first()

    def get_transactions_for_update(
        self, reference_ids: list, from_status: str, transaction_types: list = None
    ):
        qs = SkillcoinTransaction.objects.select_for_update().filter(
            reference_id__in=reference_ids,
            status=from_status,
        )
        if transaction_types:
            qs = qs.filter(transaction_type__in=transaction_types)
        return qs

    def get_transaction_total(self, wallet: UserWallet) -> Decimal:
        total = SkillcoinTransaction.objects.filter(wallet=wallet).aggregate(
            total=Sum("amount")
        )["total"]
        return total or Decimal("0.00")

    def bulk_create_status_events(self, events: list):
        TransactionStatusEvent.objects.bulk_create(events)

    def create_withdrawal_hold(self, **kwargs) -> WithdrawalHold:
        return WithdrawalHold.objects.create(**kwargs)

    def update_withdrawal_hold_status(
        self, hold_id: str, from_status: str, to_status: str
    ) -> int:
        return WithdrawalHold.objects.filter(id=hold_id, status=from_status).update(
            status=to_status
        )

    def get_all_transactions(self):
        return (
            SkillcoinTransaction.objects.select_related(
                "wallet__user", "wallet__admin_user", "admin_user"
            )
            .all()
            .order_by("-created_at")
        )

    def get_user_transactions(self, user_id: str):
        return (
            SkillcoinTransaction.objects.select_related(
                "wallet__user",
                "wallet__admin_user",
                "admin_user",
            )
            .filter(wallet__user_id=user_id)
            .order_by("-created_at")
        )

    def get_posted_revenue_total_by_wallet(
        self, wallet: UserWallet, transaction_type: str
    ) -> Decimal:
        total = SkillcoinTransaction.objects.filter(
            wallet=wallet,
            transaction_type=transaction_type,
            status=SkillcoinTransaction.Status.POSTED,
        ).aggregate(s=Sum("amount"))["s"]
        return total or Decimal("0.00")

    def get_transaction_by_reference(
        self,
        reference_id: str,
        transaction_type: str,
        wallet: "UserWallet" = None,
    ) -> Optional[SkillcoinTransaction]:
        qs = SkillcoinTransaction.objects.filter(
            reference_id=reference_id,
            transaction_type=transaction_type,
            status=SkillcoinTransaction.Status.POSTED,
        )
        if wallet is not None:
            qs = qs.filter(wallet=wallet)
        return qs.first()

    def get_user_transaction_by_ref(
        self, wallet: UserWallet, ref: str
    ) -> Optional[SkillcoinTransaction]:
        qs = SkillcoinTransaction.objects.filter(wallet=wallet)
        try:
            parsed = UUID(str(ref))
            tx = qs.filter(id=parsed).first()
            if tx:
                return tx
            return qs.filter(reference_id=parsed).first()
        except (ValueError, TypeError):
            return None

    def get_wallet_financial_stats(self, wallet: UserWallet) -> dict:
        """
        Fetches total earned, spent, and withdrawn in a single optimized query
        using exact model Enums.
        """
        stats = SkillcoinTransaction.objects.filter(
            wallet=wallet, status=SkillcoinTransaction.Status.POSTED
        ).aggregate(
            total_earned=Sum(
                Case(
                    When(
                        transaction_type__in=[
                            SkillcoinTransaction.Type.CREATOR_REVENUE,
                            SkillcoinTransaction.Type.CASHBACK_REWARD,
                            SkillcoinTransaction.Type.REGISTRATION_BONUS,
                            SkillcoinTransaction.Type.PLATFORM_REVENUE,
                        ],
                        then="amount",
                    ),
                    default=Decimal("0.00"),
                    output_field=DecimalField(),
                )
            ),
            total_spent=Sum(
                Case(
                    When(
                        transaction_type__in=[
                            SkillcoinTransaction.Type.DEBIT_PURCHASE,
                        ],
                        then="amount",
                    ),
                    default=Decimal("0.00"),
                    output_field=DecimalField(),
                )
            ),
            total_withdrawn=Sum(
                Case(
                    When(
                        transaction_type__in=[
                            SkillcoinTransaction.Type.WITHDRAWAL,
                            SkillcoinTransaction.Type.WITHDRAWAL_FEE,
                        ],
                        then="amount",
                    ),
                    default=Decimal("0.00"),
                    output_field=DecimalField(),
                )
            ),
        )

        return {
            "total_earned": stats["total_earned"] or Decimal("0.00"),
            "total_spent": stats["total_spent"] or Decimal("0.00"),
            "total_withdrawn": stats["total_withdrawn"] or Decimal("0.00"),
        }
