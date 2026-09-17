import logging
from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from skiflux.models import ActivityLog, AdminUser, Permission, User
from skiflux.models.status_events import TransactionStatusEvent
from skiflux.models.wallet import (
    SkillcoinTransaction,
    SystemFinancialConfig,
    UserWallet,
    WithdrawalHold,
)
from skiflux.repositories.wallet_repository import WalletRepository
from skiflux.services.activity import ActivityService
from skiflux.utils.exceptions import (
    InsufficientFundsError,
    WalletLockedError,
)

logger = logging.getLogger(__name__)


class WalletService:
    def __init__(self):
        self.repo = WalletRepository()

    def _get_locked_wallet(self, owner) -> UserWallet:
        wallet, _ = self.repo.get_or_create_wallet(
            owner.wallet_lookup_kwargs(), lock=True
        )
        return wallet

    def _get_locked_wallet_for_hold(self, wallet: UserWallet) -> UserWallet:
        return self.repo.get_wallet_by_pk(wallet.pk, lock=True)

    def _posted_ledger_sum(self, wallet: UserWallet) -> Decimal:
        return self.repo.get_posted_ledger_sum(wallet)

    @transaction.atomic
    def recompute_wallet_balance(self, wallet: UserWallet) -> UserWallet:
        w = self.repo.get_wallet_by_pk(wallet.pk, lock=True)
        w.balance = self._posted_ledger_sum(w)
        w.save(update_fields=["balance", "updated_at"])
        logger.info("Wallet %s balance recomputed from ledger: %s", w.id, w.balance)
        return w

    def sync_wallet_balance_from_ledger(self, wallet: UserWallet) -> UserWallet:
        return self.recompute_wallet_balance(wallet)

    @transaction.atomic
    def get_or_create_wallet(self, owner) -> UserWallet:
        """Fetch a wallet or create one atomically for User or AdminUser."""
        wallet, _ = self.repo.get_or_create_wallet(
            owner.wallet_lookup_kwargs(), lock=False
        )
        return wallet

    def _create_ledger_entry(
        self,
        wallet: UserWallet,
        amount: Decimal,
        tx_type: str,
        description: str,
        status: str = SkillcoinTransaction.Status.POSTED,
        reference_id=None,
        admin_user: AdminUser = None,
        idempotency_key: str = None,
        parent_transaction: SkillcoinTransaction = None,
    ) -> tuple[SkillcoinTransaction, bool]:
        tx, created = self.repo.create_transaction(
            wallet=wallet,
            amount=amount,
            transaction_type=tx_type,
            status=status,
            description=description,
            reference_id=reference_id,
            admin_user=admin_user,
            idempotency_key=idempotency_key,
            parent_transaction=parent_transaction,
        )
        if created:
            self.repo.create_status_event(
                skillcoin_transaction=tx,
                from_status=None,
                to_status=status,
                reason="Transaction created",
                actor=admin_user.email if admin_user else "system",
            )
        return tx, created

    @transaction.atomic
    def credit_wallet(
        self, owner, amount: Decimal, tx_type: str, description: str, **kwargs
    ) -> UserWallet:
        if amount <= Decimal("0.00"):
            raise ValidationError("Credit amount must be greater than zero.")

        wallet = self._get_locked_wallet(owner)
        if wallet.is_locked:
            raise WalletLockedError()

        tx, created = self._create_ledger_entry(
            wallet=wallet,
            amount=amount,
            tx_type=tx_type,
            description=description,
            **kwargs,
        )
        if not created:
            return wallet

        if tx.status in SkillcoinTransaction.BALANCE_STATUSES:
            wallet.balance += amount
            wallet.save(update_fields=["balance", "updated_at"])

        platform_wallet, _ = self.repo.get_platform_wallet(lock=True)
        self._create_ledger_entry(
            wallet=platform_wallet,
            amount=-amount,
            tx_type=tx_type,
            description=f"System Liability for User Credit (Ref: {tx.id})",
            status=tx.status,
            reference_id=tx.reference_id,
        )
        if tx.status in SkillcoinTransaction.BALANCE_STATUSES:
            platform_wallet.balance -= amount
            platform_wallet.save(update_fields=["balance", "updated_at"])
        return wallet

    @transaction.atomic
    def debit_wallet(
        self,
        owner,
        amount: Decimal,
        tx_type: str,
        description: str,
        **kwargs,
    ) -> UserWallet:
        if amount <= Decimal("0.00"):
            raise ValidationError("Debit amount must be greater than zero.")

        wallet = self._get_locked_wallet(owner)

        if wallet.is_locked:
            raise WalletLockedError()
        status = kwargs.get("status", SkillcoinTransaction.Status.POSTED)
        if status in SkillcoinTransaction.BALANCE_STATUSES and wallet.balance < amount:
            raise InsufficientFundsError()

        tx, created = self._create_ledger_entry(
            wallet=wallet,
            amount=-amount,
            tx_type=tx_type,
            description=description,
            **kwargs,
        )
        if not created:
            return wallet

        if status in SkillcoinTransaction.BALANCE_STATUSES:
            wallet.balance -= amount
            wallet.save(update_fields=["balance", "updated_at"])

        platform_wallet, _ = self.repo.get_platform_wallet(lock=True)
        self._create_ledger_entry(
            wallet=platform_wallet,
            amount=amount,
            tx_type=tx_type,
            description=f"System Liability Release for User Debit (Ref: {tx.id})",
            status=status,
            reference_id=tx.reference_id,
        )
        if status in SkillcoinTransaction.BALANCE_STATUSES:
            platform_wallet.balance += amount
            platform_wallet.save(update_fields=["balance", "updated_at"])
        return wallet

    @transaction.atomic
    def mark_transactions_status_by_reference(
        self,
        reference_ids: list,
        from_status: str,
        to_status: str,
        transaction_types: list = None,
    ) -> list:
        """Update ledger row status without deleting rows (audit-safe)."""
        if to_status not in dict(SkillcoinTransaction.Status.choices):
            raise ValidationError(f"Invalid transaction status: {to_status}")

        qs = self.repo.get_transactions_for_update(
            reference_ids, from_status, transaction_types
        )

        updated_ids = []

        events = []
        for tx in qs:
            old_status = tx.status
            tx.status = to_status
            tx.save(update_fields=["status"])
            events.append(
                TransactionStatusEvent(
                    skillcoin_transaction=tx,
                    from_status=old_status,
                    to_status=to_status,
                    reason="Status updated by reference",
                    actor="system",
                )
            )
            updated_ids.append(tx.id)

        if events:
            self.repo.bulk_create_status_events(events)

        return updated_ids

    @transaction.atomic
    def manual_admin_adjustment(
        self,
        admin: AdminUser,
        user: User,
        amount: Decimal,
        is_credit: bool,
        description: str,
    ) -> UserWallet:
        """Enables administrators to perform manual
        adjustments with strict auditing logs."""
        if not isinstance(admin, AdminUser) or not admin.has_permission(
            Permission.ECONOMY_MANAGE
        ):
            raise PermissionDenied(
                "You do not have administrative clearance to adjust wallet balances."
            )

        if amount <= Decimal("0.00"):
            raise ValidationError(
                "Adjustment amount must be positive and greater than zero."
            )

        config = SystemFinancialConfig.get_config()
        max_adjust = Decimal(str(config.max_manual_adjustment_amount))
        if amount > max_adjust:
            raise ValidationError(
                f"Adjustment amount cannot exceed {max_adjust} Skillcoins per operation."  # noqa: E501
            )

        desc_prefix = f"[Manual Adjust] {description.strip()}"
        if is_credit:
            wallet = self.credit_wallet(
                owner=user,
                amount=amount,
                tx_type=SkillcoinTransaction.Type.ADMIN_ADJUSTMENT,
                description=desc_prefix,
                admin_user=admin,
            )
        else:
            wallet = self.debit_wallet(
                owner=user,
                amount=amount,
                tx_type=SkillcoinTransaction.Type.ADMIN_ADJUSTMENT,
                description=desc_prefix,
                admin_user=admin,
            )
        direction = "credited" if is_credit else "debited"
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.WALLET_ADJUSTED,
            description=f"{user.email} wallet was {direction} by {amount} Skillcoins.",
            actor=admin,
            subject=user,
            metadata={
                "wallet_id": str(wallet.id),
                "amount": str(amount),
                "is_credit": is_credit,
                "description": description,
            },
        )
        return wallet

    @transaction.atomic
    def toggle_wallet_lock(
        self, admin: AdminUser, user: User, locked: bool
    ) -> UserWallet:
        """Lock or unlock a wallet. Locked wallets block all ledger activities."""
        if not isinstance(admin, AdminUser) or not admin.has_permission(
            Permission.ECONOMY_MANAGE
        ):
            raise PermissionDenied(
                "You do not have administrative clearance to lock or unlock wallets."
            )

        wallet, _ = self.repo.get_or_create_wallet({"user": user}, lock=True)
        wallet.is_locked = locked
        wallet.save(update_fields=["is_locked", "updated_at"])

        action = "locked" if locked else "unlocked"
        logger.warning(
            "Wallet for user %s was %s by admin %s", user.email, action, admin.email
        )
        ActivityService.log_activity(
            action_type=(
                ActivityLog.ActionType.WALLET_LOCKED
                if locked
                else ActivityLog.ActionType.WALLET_UNLOCKED
            ),
            description=f"{user.email} wallet was {action}.",
            actor=admin,
            subject=user,
            metadata={"wallet_id": str(wallet.id), "locked": locked},
        )
        return wallet

    @transaction.atomic
    def audit_wallet_integrity(self, user: User) -> dict:
        wallet, _ = self.repo.get_or_create_wallet({"user": user}, lock=True)

        ledger_sum = self._posted_ledger_sum(wallet)
        all_rows_sum = self.repo.get_transaction_total(wallet)

        is_valid = wallet.balance == ledger_sum

        if not is_valid:
            logger.critical(
                "CRITICAL BALANCE MISMATCH ENCOUNTERED! Wallet ID: %s, User: %s. "
                "Cached Balance: %s, Posted Ledger Sum: %s. Suspending wallet for safety.",  # noqa: E501
                wallet.id,
                user.email,
                wallet.balance,
                ledger_sum,
            )
            wallet.is_locked = True
            wallet.save(update_fields=["is_locked", "updated_at"])
            ActivityService.log_activity(
                action_type=ActivityLog.ActionType.SUSPICIOUS_ACTIVITY,
                description=(
                    f"Suspicious wallet balance mismatch detected for {user.email}."
                ),
                subject=user,
                metadata={
                    "wallet_id": str(wallet.id),
                    "cached_balance": str(wallet.balance),
                    "ledger_sum": str(ledger_sum),
                },
            )

        return {
            "wallet_id": wallet.id,
            "user_email": user.email,
            "cached_balance": wallet.balance,
            "ledger_sum": ledger_sum,
            "ledger_sum_all_rows": all_rows_sum,
            "is_valid": is_valid,
            "auto_locked": not is_valid,
        }

    @transaction.atomic
    def get_platform_wallet(self) -> UserWallet:
        """Fetch or create the singleton platform revenue wallet."""
        wallet, _ = self.repo.get_platform_wallet(lock=True)
        return wallet

    @transaction.atomic
    def credit_platform_wallet(
        self,
        amount: Decimal,
        tx_type: SkillcoinTransaction.Type,
        description: str,
        reference_id=None,
        admin_user: AdminUser = None,
        idempotency_key: str = None,
    ) -> UserWallet:
        """Credit the platform wallet."""
        if amount <= Decimal("0.00"):
            raise ValidationError("Credit amount must be greater than zero.")

        wallet = self.get_platform_wallet()
        tx, created = self._create_ledger_entry(
            wallet=wallet,
            amount=amount,
            tx_type=tx_type,
            description=description,
            reference_id=reference_id,
            admin_user=admin_user,
            idempotency_key=idempotency_key,
        )
        if not created:
            return wallet

        wallet.balance += amount
        wallet.save(update_fields=["balance", "updated_at"])
        return wallet

    @transaction.atomic
    def debit_platform_wallet(
        self,
        amount: Decimal,
        tx_type: SkillcoinTransaction.Type,
        description: str,
        reference_id=None,
        admin_user: AdminUser = None,
        idempotency_key: str = None,
    ) -> UserWallet:
        """Debit the platform wallet."""
        if amount <= Decimal("0.00"):
            raise ValidationError("Debit amount must be greater than zero.")

        wallet = self.get_platform_wallet()

        tx, created = self._create_ledger_entry(
            wallet=wallet,
            amount=-amount,
            tx_type=tx_type,
            description=description,
            reference_id=reference_id,
            admin_user=admin_user,
            idempotency_key=idempotency_key,
        )
        if not created:
            return wallet

        wallet.balance -= amount
        wallet.save(update_fields=["balance", "updated_at"])
        return wallet

    @transaction.atomic
    def mark_withdrawal_debit_as_posted(
        self,
        wallet: UserWallet,
        amount: Decimal,
    ) -> None:
        """Recomputes balance from the ledger after a pending withdrawal is posted."""
        if amount <= Decimal("0.00"):
            raise ValidationError("Amount must be positive.")

        self.recompute_wallet_balance(wallet)
        logger.info(f"Withdrawal debit posted for wallet {wallet.id}, amount {amount}")

    @transaction.atomic
    def credit_bonus_balance(
        self,
        owner,
        amount: Decimal,
        tx_type: SkillcoinTransaction.Type,
        description: str,
        idempotency_key: str = None,
    ) -> UserWallet:
        """Credits both main balance and bonus_balance atomically."""
        if amount <= Decimal("0.00"):
            raise ValidationError("Bonus amount must be greater than zero.")

        wallet = self.credit_wallet(
            owner,
            amount,
            tx_type,
            description,
            idempotency_key=idempotency_key,
        )

        # Now safely update bonus_balance under the same lock
        w = self.repo.get_wallet_by_pk(wallet.pk, lock=True)
        w.bonus_balance += amount
        w.save(update_fields=["bonus_balance", "updated_at"])

        return wallet

    @transaction.atomic
    def create_withdrawal_hold(
        self,
        owner,
        amount: Decimal,
        fee: Decimal,
        net_amount: Decimal,
        withdrawal_request=None,
    ) -> "WithdrawalHold":
        wallet = self._get_locked_wallet(owner)

        hold = self.repo.create_withdrawal_hold(
            wallet=wallet,
            withdrawal_request=withdrawal_request,
            amount=amount,
            fee=fee,
            net_amount=net_amount,
            status=WithdrawalHold.Status.ACTIVE,
        )
        return hold

    @transaction.atomic
    def release_hold(self, hold: "WithdrawalHold") -> None:
        if hold.status != hold.Status.ACTIVE:
            return

        hold.status = hold.Status.RELEASED
        hold.save(update_fields=["status", "updated_at"])

    @transaction.atomic
    def convert_hold_to_ledger(self, hold: "WithdrawalHold") -> None:
        updated = self.repo.update_withdrawal_hold_status(
            hold.id, WithdrawalHold.Status.ACTIVE, WithdrawalHold.Status.CONVERTED
        )

        if updated == 0:
            return

        hold.refresh_from_db()

        wallet = self._get_locked_wallet_for_hold(hold.wallet)

        parent_tx, _ = self._create_ledger_entry(
            wallet=wallet,
            amount=-hold.net_amount,
            tx_type=SkillcoinTransaction.Type.WITHDRAWAL,
            description=f"Withdrawal completed - Request {hold.withdrawal_request_id}",
            status=SkillcoinTransaction.Status.POSTED,
            reference_id=hold.withdrawal_request_id,
        )

        if hold.fee > 0:
            self._create_ledger_entry(
                wallet=wallet,
                amount=-hold.fee,
                tx_type=SkillcoinTransaction.Type.WITHDRAWAL_FEE,
                description=f"Withdrawal fee - Request {hold.withdrawal_request_id}",
                status=SkillcoinTransaction.Status.POSTED,
                reference_id=hold.withdrawal_request_id,
                parent_transaction=parent_tx,
            )

        wallet.balance = self._posted_ledger_sum(wallet)
        wallet.save(update_fields=["balance", "updated_at"])

    def get_active_holds_total(self, wallet: UserWallet) -> Decimal:
        return self.repo.get_active_holds_total(wallet)

    def get_withdrawable_balance(self, owner) -> Decimal:
        wallet = self.get_or_create_wallet(owner)
        if wallet.is_locked:
            return Decimal("0.00")

        active_holds = self.get_active_holds_total(wallet)
        return max(
            Decimal("0.00"), wallet.balance - wallet.bonus_balance - active_holds
        )

    def get_withdrawable_balance_from_wallet(self, wallet: UserWallet) -> Decimal:
        if wallet.is_locked:
            return Decimal("0.00")

        active_holds = self.get_active_holds_total(wallet)
        return max(
            Decimal("0.00"), wallet.balance - wallet.bonus_balance - active_holds
        )

    def get_user_financial_summary(self, user) -> dict:
        wallet = self.repo.get_wallet({"user": user})

        if not wallet:
            return {
                "total_earned": Decimal("0.00"),
                "total_spent": Decimal("0.00"),
                "total_withdrawn": Decimal("0.00"),
            }

        stats = self.repo.get_wallet_financial_stats(wallet)

        return stats

    def get_user_transactions(self, user_id: str):
        transaction = self.repo.get_user_transactions(user_id)
        return transaction

    def report_transaction(
        self, user, ref: str, reason: str, details: str = ""
    ) -> dict:
        from skiflux.models.support import SupportTicket
        from skiflux.repositories.support_repository import SupportRepository

        wallet = self.get_or_create_wallet(user)
        tx = self.repo.get_user_transaction_by_ref(wallet, ref)
        if not tx:
            raise ValidationError("Transaction not found.")

        body_lines = [
            f"Transaction ID: {tx.id}",
            f"Amount: {tx.amount}",
            f"Type: {tx.transaction_type}",
            f"Status: {tx.status}",
            f"Description: {tx.description}",
        ]
        if tx.reference_id:
            body_lines.append(f"Reference ID: {tx.reference_id}")
        body_lines.extend(["", f"Reason: {reason}"])
        if details:
            body_lines.extend(["", f"Details: {details}"])

        ticket = SupportRepository().create_ticket(
            user=user,
            sender_email=user.email,
            sender_name=user.first_name,
            subject=f"Transaction report: {tx.id}",
            category=SupportTicket.Category.FAILED_TRANSACTION,
            body="\n".join(body_lines),
        )
        return {
            "case_id": ticket.id,
            "status": ticket.status,
            "ticket_number": ticket.ticket_number,
        }
