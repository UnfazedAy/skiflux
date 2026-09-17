import uuid
from decimal import Decimal

import pytest

from skiflux.models import User
from skiflux.models.wallet import SkillcoinTransaction
from skiflux.services.wallet_service import WalletService


@pytest.fixture
def wallet_service():
    return WalletService()


@pytest.fixture
def test_user(db):
    return User.objects.create(
        email="invariant@test.com", first_name="Inv", password="pwd"
    )


@pytest.mark.django_db
class TestWalletBalanceInvariants:
    """Critical financial integrity tests."""

    def test_balance_always_matches_posted_ledger_after_operations(
        self, wallet_service, test_user
    ):
        """The most important invariant: cached
        balance must equal sum of posted ledger entries."""
        ws = wallet_service

        # Perform a realistic sequence of operations
        ws.credit_wallet(
            test_user, Decimal("1000.00"), SkillcoinTransaction.Type.TOPUP, "Topup 1"
        )
        ws.credit_wallet(
            test_user,
            Decimal("250.00"),
            SkillcoinTransaction.Type.REGISTRATION_BONUS,
            "Bonus",
        )
        ws.debit_wallet(
            test_user,
            Decimal("300.00"),
            SkillcoinTransaction.Type.DEBIT_PURCHASE,
            "Purchase",
        )

        wallet = ws.get_or_create_wallet(test_user)
        ledger_sum = ws._posted_ledger_sum(wallet)

        assert wallet.balance == ledger_sum, (
            f"CRITICAL INVARIANT VIOLATION: balance={wallet.balance} != ledger_sum={ledger_sum}"  # noqa: E501
        )

    def test_withdrawal_flow_does_not_break_invariant(self, wallet_service, test_user):
        """Regression test for the old direct mutation bug."""
        ws = wallet_service
        withdrawal_ref = uuid.uuid4()
        ws.credit_wallet(
            test_user, Decimal("5000.00"), SkillcoinTransaction.Type.TOPUP, "Initial"
        )
        ws.debit_wallet(
            test_user,
            Decimal("1000.00"),
            SkillcoinTransaction.Type.WITHDRAWAL,
            "Withdrawal request",
            reference_id=withdrawal_ref,
            status=SkillcoinTransaction.Status.PENDING,
        )

        wallet = ws.get_or_create_wallet(test_user)
        assert wallet.balance == Decimal("5000.00")

        ws.mark_transactions_status_by_reference(
            reference_ids=[withdrawal_ref],
            from_status=SkillcoinTransaction.Status.PENDING,
            to_status=SkillcoinTransaction.Status.POSTED,
        )
        # Simulate what mark_withdrawal_completed used to do (via the new safe method)
        ws.mark_withdrawal_debit_as_posted(wallet, Decimal("1000.00"))
        wallet.refresh_from_db()
        ledger_sum = ws._posted_ledger_sum(wallet)
        assert wallet.balance == Decimal("4000.00")
        assert wallet.balance == ledger_sum
