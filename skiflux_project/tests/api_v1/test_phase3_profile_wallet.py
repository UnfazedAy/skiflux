from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.content import Follow
from skiflux.models.support import SupportTicket
from skiflux.models.wallet import SkillcoinTransaction
from skiflux.services.wallet_service import WalletService

from .conftest import (
    make_creator,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class TransactionReportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="wallet-report@example.com")
        self.client = user_auth_client(self.user)
        self.wallet = WalletService().get_or_create_wallet(self.user)
        self.tx = SkillcoinTransaction.objects.create(
            wallet=self.wallet,
            amount=Decimal("100.00"),
            transaction_type=SkillcoinTransaction.Type.TOPUP,
            status=SkillcoinTransaction.Status.POSTED,
            description="Test top-up",
        )

    def test_report_transaction_by_id(self):
        resp = self.client.post(
            f"{BASE}/wallet/transactions/{self.tx.id}/report",
            {"reason": "Wrong amount", "details": "Charged twice"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.data["data"]
        self.assertIn("case_id", data)
        self.assertEqual(data["status"], SupportTicket.Status.OPEN)
        ticket = SupportTicket.objects.get(id=data["case_id"])
        self.assertEqual(ticket.category, SupportTicket.Category.FAILED_TRANSACTION)
        self.assertEqual(ticket.user_id, self.user.id)

    def test_report_transaction_not_found(self):
        import uuid

        resp = self.client.post(
            f"{BASE}/wallet/transactions/{uuid.uuid4()}/report",
            {"reason": "Missing tx"},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)


class AppPreferencesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="app-prefs@example.com")
        self.client = user_auth_client(self.user)

    def test_get_default_app_preferences(self):
        resp = self.client.get(f"{BASE}/me/app-preferences")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertTrue(data["auto_play_next"])
        self.assertEqual(data["download_quality"], "standard")
        self.assertTrue(data["save_watch_history"])

    def test_patch_app_preferences(self):
        resp = self.client.patch(
            f"{BASE}/me/app-preferences/update",
            {
                "auto_play_next": False,
                "download_quality": "data_saver",
                "app_language": "fr",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["auto_play_next"])
        self.assertEqual(resp.data["data"]["download_quality"], "data_saver")
        self.assertEqual(resp.data["data"]["app_language"], "fr")


class CreatorNotificationPreferenceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="creator-notify@example.com")
        self.creator = make_creator(username="notifycreator")
        self.client = user_auth_client(self.user)
        Follow.objects.create(
            follower=self.user,
            creator=self.creator,
            notifications_enabled=True,
            notification_mode=Follow.NotificationMode.ALL,
        )

    def test_get_creator_notification_preference(self):
        resp = self.client.get(
            f"{BASE}/me/creator-notification-preferences/{self.creator.id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["mode"], "all")

    def test_patch_creator_notification_preference(self):
        resp = self.client.patch(
            f"{BASE}/me/creator-notification-preferences/{self.creator.id}",
            {"mode": "none"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["mode"], "none")
        follow = Follow.objects.get(follower=self.user, creator=self.creator)
        self.assertFalse(follow.notifications_enabled)
        self.assertEqual(follow.notification_mode, Follow.NotificationMode.NONE)

    def test_creator_profile_includes_notification_mode_when_following(self):
        resp = self.client.get(f"{BASE}/creators/{self.creator.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["notification_mode"], "all")

    def test_not_following_returns_404_for_preference(self):
        import uuid

        resp = self.client.get(
            f"{BASE}/me/creator-notification-preferences/{uuid.uuid4()}"
        )
        self.assertEqual(resp.status_code, 404)
