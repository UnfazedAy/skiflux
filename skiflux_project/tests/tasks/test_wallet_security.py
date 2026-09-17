from decimal import Decimal

from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied, ValidationError

from skiflux.models import AdminUser, Permission, Role, User
from skiflux.models.wallet import SkillcoinTransaction, UserWallet
from skiflux.services.wallet_service import WalletService


class WalletSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="wallet_test@example.com", first_name="Skill", password="StrongPass1!"
        )
        self.economy_role = Role.objects.create(
            name="Economy Manager",
            permissions=[Permission.ECONOMY_VIEW, Permission.ECONOMY_MANAGE],
        )
        self.admin = AdminUser.objects.create_admin(
            email="finance_admin@example.com",
            first_name="Auditor",
            password="SafePassword2!",
            roles=[self.economy_role],
        )
        self.unauthorized_admin = AdminUser.objects.create_admin(
            email="unauth_admin@example.com",
            first_name="Rogue",
            password="SafePassword3!",
        )
        self.wallet_service = WalletService()

    def test_wallet_created_on_demand(self):
        wallet = self.wallet_service.get_or_create_wallet(self.user)
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.balance, Decimal("0.00"))
        self.assertFalse(wallet.is_locked)

    def test_secure_credits_and_debits(self):
        self.wallet_service.credit_wallet(
            self.user,
            Decimal("100.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Deposit Top-up",
        )
        wallet = UserWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, Decimal("100.00"))
        self.assertEqual(wallet.transactions.count(), 1)
        self.assertEqual(wallet.transactions.first().amount, Decimal("100.00"))

        self.wallet_service.debit_wallet(
            self.user,
            Decimal("35.50"),
            SkillcoinTransaction.Type.DEBIT_PURCHASE,
            "Purchased Premium Episode",
        )
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("64.50"))
        self.assertEqual(wallet.transactions.count(), 2)
        debit_tx = wallet.transactions.filter(amount__lt=0).first()
        self.assertEqual(debit_tx.amount, Decimal("-35.50"))

    def test_insufficient_funds_fails(self):
        self.wallet_service.credit_wallet(
            self.user,
            Decimal("20.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Small Deposit",
        )
        with self.assertRaises(ValidationError) as ctx:
            self.wallet_service.debit_wallet(
                self.user,
                Decimal("20.01"),
                SkillcoinTransaction.Type.DEBIT_PURCHASE,
                "Overdraft purchase attempt",
            )
        self.assertIn("Insufficient Skillcoin balance", str(ctx.exception))

    def test_database_level_negative_constraint(self):
        wallet = self.wallet_service.get_or_create_wallet(self.user)
        with self.assertRaises(IntegrityError):
            UserWallet.objects.filter(id=wallet.id).update(balance=Decimal("-10.00"))

    def test_locked_wallet_blocks_transactions(self):
        wallet = self.wallet_service.get_or_create_wallet(self.user)
        self.wallet_service.toggle_wallet_lock(self.admin, self.user, locked=True)
        wallet.refresh_from_db()
        self.assertTrue(wallet.is_locked)

        # Attempted credit should raise validation error
        with self.assertRaises(ValidationError) as ctx:
            self.wallet_service.credit_wallet(
                self.user,
                Decimal("100.00"),
                SkillcoinTransaction.Type.DEPOSIT,
                "Credit attempt on locked",
            )
        self.assertIn("locked", str(ctx.exception))

        # Attempted debit should raise validation error
        with self.assertRaises(ValidationError) as ctx:
            self.wallet_service.debit_wallet(
                self.user,
                Decimal("10.00"),
                SkillcoinTransaction.Type.DEBIT_PURCHASE,
                "Debit attempt on locked",
            )
        self.assertIn("locked", str(ctx.exception))

    def test_unauthorized_admin_fails_actions(self):
        with self.assertRaises(PermissionDenied):
            self.wallet_service.toggle_wallet_lock(
                self.unauthorized_admin, self.user, locked=True
            )

        with self.assertRaises(PermissionDenied):
            self.wallet_service.manual_admin_adjustment(
                self.unauthorized_admin,
                self.user,
                Decimal("50.00"),
                is_credit=True,
                description="Rogue Adjustment",
            )

    def test_valid_admin_can_adjust_balance(self):
        wallet = self.wallet_service.manual_admin_adjustment(
            self.admin,
            self.user,
            Decimal("500.00"),
            is_credit=True,
            description="Comped reward",
        )
        self.assertEqual(wallet.balance, Decimal("500.00"))
        tx = SkillcoinTransaction.objects.get(wallet=wallet)
        self.assertEqual(tx.admin_user, self.admin)
        self.assertIn("Comped reward", tx.description)

    def test_double_entry_ledger_integrity_check(self):
        self.wallet_service.credit_wallet(
            self.user, Decimal("100.00"), SkillcoinTransaction.Type.DEPOSIT, "Init"
        )
        audit_results = self.wallet_service.audit_wallet_integrity(self.user)
        self.assertTrue(audit_results["is_valid"])

        UserWallet.objects.filter(user=self.user).update(balance=Decimal("9999.00"))

        cache.clear()
        self.user.refresh_from_db()

        audit_results2 = self.wallet_service.audit_wallet_integrity(self.user)
        self.assertFalse(audit_results2["is_valid"])
        self.assertTrue(audit_results2["auto_locked"])

        wallet = UserWallet.objects.get(user=self.user)
        self.assertTrue(wallet.is_locked)
