from decimal import Decimal

import pytest

from skiflux.models import AdminUser, User
from skiflux.models.wallet import (
    SkillcoinTransaction,
)
from skiflux.services.wallet_service import WalletService


@pytest.fixture
def wallet_service():
    return WalletService()


@pytest.fixture
def test_user(db):
    return User.objects.create(email="user@test.com", password="pwd")


@pytest.fixture
def test_admin(db):
    return AdminUser.objects.create(email="admin@test.com", password="pwd")


@pytest.mark.django_db
class TestWalletService:
    def test_platform_wallet_creation(self, wallet_service):
        wallet = wallet_service.get_platform_wallet()
        assert wallet.is_platform_wallet is True
        assert wallet.balance == Decimal("0.00")

        # Verify singleton behavior
        wallet2 = wallet_service.get_platform_wallet()
        assert wallet.id == wallet2.id

    def test_credit_wallet_idempotency(self, wallet_service, test_user):
        amount = Decimal("500.00")
        idemp_key = "credit-test-123"

        # First credit
        wallet_service.credit_wallet(
            owner=test_user,
            amount=amount,
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Test credit",
            idempotency_key=idemp_key,
        )
        wallet = wallet_service.get_or_create_wallet(test_user)
        assert wallet.balance == amount

        # Second credit with SAME key should be ignored
        wallet_service.credit_wallet(
            owner=test_user,
            amount=amount,
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Test credit",
            idempotency_key=idemp_key,
        )
        wallet.refresh_from_db()
        assert wallet.balance == amount  # Balance shouldn't double

        # Verify ledger rows
        assert (
            SkillcoinTransaction.objects.filter(idempotency_key=idemp_key).count() == 1
        )

    def test_debit_wallet_insufficient_funds(self, wallet_service, test_user):
        from skiflux.utils.exceptions import InsufficientFundsError

        with pytest.raises(
            InsufficientFundsError, match="Insufficient Skillcoin balance."
        ):
            wallet_service.debit_wallet(
                owner=test_user,
                amount=Decimal("10.00"),
                tx_type=SkillcoinTransaction.Type.WITHDRAWAL,
                description="Too poor to withdraw",
            )

    def test_wallet_lock_prevents_transactions(
        self, wallet_service, test_user, test_admin
    ):
        # Create permissions setup assuming basic setup
        # Lock the wallet
        wallet = wallet_service.get_or_create_wallet(test_user)
        wallet.is_locked = True
        wallet.save()

        from skiflux.utils.exceptions import WalletLockedError

        with pytest.raises(
            WalletLockedError,
            match="Transaction rejected. Wallet is currently suspended/locked.",
        ):
            wallet_service.credit_wallet(
                owner=test_user,
                amount=Decimal("100.00"),
                tx_type=SkillcoinTransaction.Type.TOPUP,
                description="Should fail",
            )

    def test_ledger_immutability(self, wallet_service, test_user):
        wallet_service.credit_wallet(
            owner=test_user,
            amount=Decimal("100.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Test credit",
        )
        tx = SkillcoinTransaction.objects.first()

        # Prevent deletion
        with pytest.raises(PermissionError):
            tx.delete()

        # Prevent modification of amount
        tx.amount = Decimal("9999.00")
        with pytest.raises(PermissionError):
            tx.save()
