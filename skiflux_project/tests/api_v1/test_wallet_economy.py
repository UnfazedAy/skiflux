"""
Wallet economy tests: financial config API, registration bonus, purchase race safety,
refund clawback, cashback cap, manual adjustment cap, approve submission.
"""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from skiflux.models import User
from skiflux.models.content import Episode, EpisodePurchase, EpisodeTask, TaskSubmission
from skiflux.models.role import Permission
from skiflux.models.wallet import (
    SkillcoinTransaction,
    SystemFinancialConfig,
    UserWallet,
)
from skiflux.repositories.wallet_repository import WalletRepository
from skiflux.services.auth_service import AuthService
from skiflux.services.content_service import ContentService
from skiflux.services.registration_bonus_service import REGISTRATION_BONUS_DESCRIPTION
from skiflux.services.wallet_service import WalletService
from skiflux.utils import set_email_verification_otp

from .conftest import (
    admin_auth_client,
    make_admin_with_role,
    make_creator,
    make_episode,
    make_season,
    make_super_admin,
    make_verified_user,
)

BASE = "/api/v1"


class FinancialConfigAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.super_client = admin_auth_client(self.super_admin)
        economy_admin, role = make_admin_with_role(
            [Permission.ECONOMY_VIEW, Permission.ECONOMY_MANAGE],
            email="economy@skiflux.com",
        )
        self.economy_client = admin_auth_client(economy_admin)
        self.economy_role = role

    def test_financial_config_get_returns_200(self):
        resp = self.economy_client.get(f"{BASE}/admin/finance/financial-config")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("registration_bonus_skillcoins", resp.data["data"])
        self.assertIn("episode_purchase_price_skillcoins", resp.data["data"])

    def test_super_admin_can_patch_episode_purchase_price(self):
        resp = self.super_client.patch(
            f"{BASE}/admin/finance/financial-config",
            {"episode_purchase_price_skillcoins": "30.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        config = SystemFinancialConfig.get_config()
        self.assertEqual(config.episode_purchase_price_skillcoins, Decimal("30.00"))

    def test_super_admin_can_patch_financial_config(self):
        resp = self.super_client.patch(
            f"{BASE}/admin/finance/financial-config",
            {
                "registration_bonus_skillcoins": "25.00",
                "max_cashback_amount": "50.00",
                "max_manual_adjustment_amount": "500.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        config = SystemFinancialConfig.get_config()
        self.assertEqual(config.registration_bonus_skillcoins, Decimal("25.00"))
        self.assertEqual(config.max_cashback_amount, Decimal("50.00"))

    def test_non_super_admin_patch_financial_config_forbidden(self):
        resp = self.economy_client.patch(
            f"{BASE}/admin/finance/financial-config",
            {"registration_bonus_skillcoins": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class RegistrationBonusTests(TestCase):
    def setUp(self):
        cache.clear()
        config = SystemFinancialConfig.get_config()
        config.registration_bonus_skillcoins = Decimal("15.00")
        config.save()

    def test_verify_email_grants_bonus_once(self):
        user = User.objects.create_user(
            email="bonus@example.com",
            first_name="Bonus",
            password="StrongPass1!",
            is_verified=False,
        )
        set_email_verification_otp(user.email, "123456")
        AuthService().verify_email(user.email, "123456")
        user.refresh_from_db()
        self.assertTrue(user.registration_bonus_granted)
        wallet = UserWallet.objects.get(user=user)
        self.assertEqual(wallet.balance, Decimal("15.00"))
        self.assertEqual(
            SkillcoinTransaction.objects.filter(
                wallet=wallet,
                transaction_type=SkillcoinTransaction.Type.REGISTRATION_BONUS,
                description=REGISTRATION_BONUS_DESCRIPTION,
            ).count(),
            1,
        )

        AuthService().registration_bonus_service.grant_if_eligible(user)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("15.00"))


class PurchaseAndRefundTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="buyer@example.com")
        self.creator = make_creator(email="sellcreator@skiflux.com")
        self.season = make_season(self.creator)
        config = SystemFinancialConfig.get_config()
        config.episode_purchase_price_skillcoins = Decimal("100.00")
        config.save()
        self.episode = make_episode(
            self.creator,
            self.season,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.PUBLISHED,
        )
        WalletService().credit_wallet(
            self.user,
            Decimal("200.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Fund buyer",
        )
        WalletService().get_or_create_wallet(self.creator)

    def test_refund_claws_back_creator_revenue_share(self):
        ContentService().purchase_episode(self.user, str(self.episode.id))
        purchase = EpisodePurchase.objects.get(user=self.user, episode=self.episode)
        creator_wallet, _ = WalletRepository().get_or_create_wallet(
            {"admin_user": self.creator}
        )
        creator_wallet.balance = Decimal("1000.00")
        creator_wallet.save()
        self.assertEqual(creator_wallet.balance, Decimal("70.00"))

        economy_admin, _ = make_admin_with_role(
            [Permission.ECONOMY_MANAGE],
            email="refundadmin@skiflux.com",
        )
        ContentService().refund_episode_purchase(economy_admin, str(purchase.id))

        creator_wallet.refresh_from_db()
        buyer_wallet = UserWallet.objects.get(user=self.user)
        self.assertEqual(creator_wallet.balance, Decimal("0.00"))
        self.assertEqual(buyer_wallet.balance, Decimal("200.00"))

        purchase.refresh_from_db()
        self.assertEqual(purchase.status, EpisodePurchase.Status.REFUNDED)
        self.assertTrue(
            SkillcoinTransaction.objects.filter(
                wallet__user=self.user,
                transaction_type=SkillcoinTransaction.Type.DEBIT_PURCHASE,
                status=SkillcoinTransaction.Status.REFUNDED,
            ).exists()
        )
        self.assertTrue(
            SkillcoinTransaction.objects.filter(
                wallet__user=self.user,
                transaction_type=SkillcoinTransaction.Type.REFUND,
                status=SkillcoinTransaction.Status.POSTED,
            ).exists()
        )


class CashbackAndManualAdjustTests(TestCase):
    def setUp(self):
        cache.clear()
        config = SystemFinancialConfig.get_config()
        config.max_cashback_amount = Decimal("30.00")
        config.max_manual_adjustment_amount = Decimal("40.00")
        config.save()
        self.user = make_verified_user(email="cashback@example.com")
        self.creator = make_creator()
        self.season = make_season(self.creator)
        config = SystemFinancialConfig.get_config()
        config.episode_purchase_price_skillcoins = Decimal("10.00")
        config.save()
        self.episode = make_episode(
            self.creator,
            self.season,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.PUBLISHED,
        )
        self.task = EpisodeTask.objects.create(
            episode=self.episode,
            kind="text",
            completion_criteria={"min_words": 10},
        )
        WalletService().credit_wallet(
            self.user,
            Decimal("50.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Test funds",
        )
        ContentService().purchase_episode(self.user, str(self.episode.id))
        self.submission = TaskSubmission.objects.create(
            task=self.task,
            user=self.user,
            submission_text="Done",
        )
        self.content_admin, _ = make_admin_with_role(
            [Permission.CONTENT_MANAGE],
            email="contentadmin@skiflux.com",
        )

    def test_cashback_respects_config_cap(self):
        with self.assertRaises(ValidationError):
            ContentService().approve_submission(
                self.content_admin,
                str(self.submission.id),
                cashback_amount=31.0,
            )

    def test_manual_adjustment_respects_config_cap(self):
        economy_admin, _ = make_admin_with_role(
            [Permission.ECONOMY_MANAGE],
            email="capadmin@skiflux.com",
        )
        wallet_service = WalletService()
        with self.assertRaises(ValidationError):
            wallet_service.manual_admin_adjustment(
                economy_admin,
                self.user,
                Decimal("41.00"),
                is_credit=True,
                description="Too large",
            )


class ApproveSubmissionAPITests(TestCase):
    def setUp(self):
        cache.clear()
        config = SystemFinancialConfig.get_config()
        config.max_cashback_amount = Decimal("100.00")
        config.episode_purchase_price_skillcoins = Decimal("5.00")
        config.save()
        self.user = make_verified_user(email="submit@example.com")
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.PUBLISHED,
        )
        self.task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            completion_criteria={},
        )
        wallet_service = WalletService()
        wallet_service.credit_wallet(
            self.user,
            Decimal("50.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Test funds",
        )
        wallet_service.credit_platform_wallet(
            Decimal("50.00"),
            SkillcoinTransaction.Type.PLATFORM_REVENUE,
            "Test funds",
        )
        ContentService().purchase_episode(self.user, str(self.episode.id))
        self.submission = TaskSubmission.objects.create(
            task=self.task,
            user=self.user,
            submission_text="Answer",
        )
        self.admin, _ = make_admin_with_role(
            [Permission.CONTENT_MANAGE],
            email="approve@skiflux.com",
        )
        self.client = admin_auth_client(self.admin)

    def test_approve_submission_endpoint_awards_cashback(self):
        resp = self.client.post(
            f"{BASE}/admin/content/submissions/{self.submission.id}/approve",
            {"cashback_amount": "12.50"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        wallet = UserWallet.objects.get(user=self.user)
        # 50 funded - 5 purchase + 12.50 cashback
        self.assertEqual(wallet.balance, Decimal("57.50"))


class PurchaseIdempotencyTests(TestCase):
    """Purchase is claimed via get_or_create before debiting to prevent double spend."""

    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="race@example.com")
        self.creator = make_creator(email="racecreator@skiflux.com")
        self.season = make_season(self.creator)
        config = SystemFinancialConfig.get_config()
        config.episode_purchase_price_skillcoins = Decimal("10.00")
        config.save()
        self.episode = make_episode(
            self.creator,
            self.season,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.PUBLISHED,
        )
        WalletService().credit_wallet(
            self.user,
            Decimal("1000.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Fund",
        )

    def test_second_purchase_attempt_rejected_without_extra_debit(self):
        service = ContentService()
        service.purchase_episode(self.user, str(self.episode.id))
        with self.assertRaises(ValidationError):
            service.purchase_episode(self.user, str(self.episode.id))

        self.assertEqual(
            EpisodePurchase.objects.filter(
                user=self.user, episode=self.episode
            ).count(),
            1,
        )
        wallet = UserWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, Decimal("990.00"))
