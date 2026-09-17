"""
Mobile backend reconciliation tests (2026-07-31 feedback).
"""

import uuid
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.content import (
    Episode,
)
from skiflux.models.notification import Notification
from skiflux.models.wallet import SystemFinancialConfig

from .conftest import (
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class CreatorCatalogueTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.client = user_auth_client(self.user)
        self.creator = make_creator(username="catalogcreator")
        self.other_creator = make_creator(
            email="other@skiflux.com",
            username="othercreator",
        )

        self.published_season = make_season(
            self.creator,
            title="Creator Season",
            skillworld="design",
        )
        self.published_season.is_published = True
        self.published_season.cover_image_public_id = "seasons/creator-cover"
        self.published_season.save()

        self.other_season = make_season(
            self.creator,
            title="Code Season",
            skillworld="code",
        )
        self.other_season.is_published = True
        self.other_season.save()

        self.draft_season = make_season(
            self.creator,
            title="Draft Season",
            skillworld="design",
        )
        self.draft_season.is_published = False
        self.draft_season.save()

        self.episode = make_episode(
            self.creator,
            self.published_season,
            order=1,
            title="Catalog Episode",
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.PAID,
        )
        make_episode(
            self.creator,
            self.other_season,
            order=1,
            title="Code Episode",
            status=Episode.Status.PUBLISHED,
        )
        make_episode(
            self.creator,
            self.draft_season,
            order=1,
            title="Hidden Episode",
            status=Episode.Status.PUBLISHED,
        )

    def test_creator_seasons_returns_published_only(self):
        resp = self.client.get(f"{BASE}/creators/{self.creator.id}/seasons")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        titles = {item["title"] for item in results}
        self.assertIn("Creator Season", titles)
        self.assertIn("Code Season", titles)
        self.assertNotIn("Draft Season", titles)
        season = next(r for r in results if r["title"] == "Creator Season")
        self.assertIn("cover_url", season)
        self.assertTrue(season["cover_url"])
        self.assertEqual(season["episode_count"], 1)

    def test_creator_seasons_skillworld_filter(self):
        resp = self.client.get(
            f"{BASE}/creators/{self.creator.id}/seasons?skillworld=design"
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["skillworld"], "design")

    def test_creator_episodes_include_lock_fields(self):
        resp = self.client.get(f"{BASE}/creators/{self.creator.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertEqual(len(results), 2)
        paid = next(r for r in results if r["title"] == "Catalog Episode")
        self.assertTrue(paid["is_locked"])
        self.assertFalse(paid["is_purchased"])
        self.assertIsNotNone(paid["skillcoin_price"])

    def test_creator_episodes_skillworld_filter(self):
        resp = self.client.get(
            f"{BASE}/creators/{self.creator.id}/episodes?skillworld=code"
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Code Episode")

    def test_creator_catalogue_not_found(self):
        resp = self.client.get(f"{BASE}/creators/{uuid.uuid4()}/episodes")
        self.assertEqual(resp.status_code, 404)


class ProfileOnboardedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.user.is_onboarded = False
        self.user.save(update_fields=["is_onboarded"])
        self.client = user_auth_client(self.user)

    def test_profile_includes_is_onboarded(self):
        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["is_onboarded"])


class WithdrawalMethodsFeeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.client = user_auth_client(self.user)
        config = SystemFinancialConfig.get_config()
        config.withdrawal_fee_percentage = Decimal("2.50")
        config.save()

    def test_withdrawal_methods_include_fee_percentage(self):
        resp = self.client.get(f"{BASE}/wallet/withdrawals/methods")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["withdrawal_fee_percentage"], "2.50")
        self.assertIsInstance(data["methods"], list)


class MarkAllNotificationsReadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.client = user_auth_client(self.user)
        Notification.objects.create(
            user=self.user,
            type="platform_announcement",
            title="One",
            body="Body",
            data={},
            is_read=False,
        )
        Notification.objects.create(
            user=self.user,
            type="platform_announcement",
            title="Two",
            body="Body",
            data={},
            is_read=True,
        )

    def test_mark_all_read_is_idempotent(self):
        resp = self.client.post(f"{BASE}/me/notifications/mark-all-read")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["updated_count"], 1)
        self.assertFalse(
            Notification.objects.filter(user=self.user, is_read=False).exists()
        )
        resp2 = self.client.post(f"{BASE}/me/notifications/mark-all-read")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data["data"]["updated_count"], 0)
