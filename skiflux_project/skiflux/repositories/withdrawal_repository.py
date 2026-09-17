from typing import Optional
from skiflux.models.wallet import WithdrawalAccount, WithdrawalRequest, WithdrawalHold
from skiflux.models.status_events import TransactionStatusEvent


class WithdrawalRepository:
    def create_withdrawal_account(self, **kwargs) -> WithdrawalAccount:
        return WithdrawalAccount.objects.create(**kwargs)

    def get_withdrawal_accounts_count(self, user=None, admin_user=None) -> int:
        return WithdrawalAccount.objects.filter(
            user=user, admin_user=admin_user, is_active=True
        ).count()

    def get_withdrawal_account_by_id(
        self, account_id: str, *, active_only: bool = False
    ) -> Optional[WithdrawalAccount]:
        qs = WithdrawalAccount.objects.filter(id=account_id)
        if active_only:
            qs = qs.filter(is_active=True)
        return qs.first()

    def get_owned_withdrawal_account(
        self,
        account_id: str,
        *,
        user=None,
        admin_user=None,
        active_only: bool = True,
    ) -> Optional[WithdrawalAccount]:
        qs = WithdrawalAccount.objects.filter(
            id=account_id, user=user, admin_user=admin_user
        )
        if active_only:
            qs = qs.filter(is_active=True)
        return qs.first()

    def has_open_withdrawal_requests(self, account: WithdrawalAccount) -> bool:
        return WithdrawalRequest.objects.filter(
            withdrawal_account=account,
            status__in=[
                WithdrawalRequest.Status.PENDING,
                WithdrawalRequest.Status.PROCESSING,
            ],
        ).exists()

    def deactivate_withdrawal_account(self, account: WithdrawalAccount) -> None:
        account.is_active = False
        account.is_default = False
        account.save(update_fields=["is_active", "is_default", "updated_at"])

    def set_default_withdrawal_account(self, account: WithdrawalAccount) -> None:
        WithdrawalAccount.objects.filter(
            user=account.user,
            admin_user=account.admin_user,
            is_active=True,
        ).exclude(id=account.id).update(is_default=False, updated_at=account.updated_at)
        account.is_default = True
        account.save(update_fields=["is_default", "updated_at"])

    def get_next_default_withdrawal_account(
        self, *, user=None, admin_user=None, exclude_id=None
    ) -> Optional[WithdrawalAccount]:
        qs = WithdrawalAccount.objects.filter(
            user=user,
            admin_user=admin_user,
            is_active=True,
            status=WithdrawalAccount.Status.VERIFIED,
        ).order_by("-is_default", "created_at")
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        return qs.first()

    def create_withdrawal_request(self, **kwargs) -> WithdrawalRequest:
        return WithdrawalRequest.objects.create(**kwargs)

    def get_withdrawal_request_for_update(
        self, request_id: str
    ) -> Optional[WithdrawalRequest]:
        return (
            WithdrawalRequest.objects.select_for_update().filter(id=request_id).first()
        )

    def get_withdrawal_request_by_id(
        self, request_id: str
    ) -> Optional[WithdrawalRequest]:
        return WithdrawalRequest.objects.filter(id=request_id).first()

    def update_withdrawal_request_status(
        self, request_id: str, from_status, to_status: str, processed_at=None
    ) -> int:
        """Atomically transition a request's status. ``from_status`` may be a
        single status or a list/tuple of allowed source statuses; the UPDATE
        matches at most one row, so concurrent callers race safely."""
        if isinstance(from_status, (list, tuple)):
            qs = WithdrawalRequest.objects.filter(id=request_id, status__in=from_status)
        else:
            qs = WithdrawalRequest.objects.filter(id=request_id, status=from_status)
        update_kwargs = {"status": to_status}
        if processed_at:
            update_kwargs["processed_at"] = processed_at
        return qs.update(**update_kwargs)

    def create_status_event(self, **kwargs) -> TransactionStatusEvent:
        return TransactionStatusEvent.objects.create(**kwargs)

    def create_withdrawal_hold(self, **kwargs) -> WithdrawalHold:
        return WithdrawalHold.objects.create(**kwargs)

    def update_withdrawal_hold_status(
        self, hold_id: str, from_status: str, to_status: str
    ) -> int:
        return WithdrawalHold.objects.filter(id=hold_id, status=from_status).update(
            status=to_status
        )
