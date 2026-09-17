"""
Season catalogue list tests.
Endpoint: GET /api/v1/seasons
"""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.content import Episode
from skiflux.services.content_service import ContentService
from skiflux.services.wallet_service import WalletService
from skiflux.models.wallet import SkillcoinTransaction, SystemFinancialConfig

from .conftest import (
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class ListSeasonsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.published_season = make_season(
            self.creator,
            title="Published Season",
            skillworld="design",
        )
        self.published_season.is_published = True
        self.published_season.cover_image_public_id = "seasons/cover123"
        self.published_season.save()
        make_episode(
            self.creator,
            self.published_season,
            order=1,
            status=Episode.Status.PUBLISHED,
            title="Episode A",
        )
        make_episode(
            self.creator,
            self.published_season,
            order=2,
            status=Episode.Status.DRAFT,
            title="Draft Episode",
        )

        self.draft_season = make_season(
            self.creator,
            title="Draft Season",
            skillworld="code",
        )
        self.draft_season.is_published = False
        self.draft_season.save()

    def test_list_seasons_returns_only_published(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        ids = [item["id"] for item in results]
        self.assertIn(str(self.published_season.id), ids)
        self.assertNotIn(str(self.draft_season.id), ids)

    def test_list_seasons_item_shape(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons")
        self.assertEqual(resp.status_code, 200)
        season = resp.data["data"]["results"][0]
        self.assertIn("id", season)
        self.assertIn("title", season)
        self.assertIn("description", season)
        self.assertIn("cover_url", season)
        self.assertIn("creator", season)
        self.assertIn("episode_count", season)
        self.assertIn("skillworld", season)
        self.assertIn("id", season["creator"])
        self.assertIn("username", season["creator"])
        self.assertIn("display_name", season["creator"])
        self.assertEqual(season["episode_count"], 1)

    def test_list_seasons_filter_by_skillworld(self):
        code_season = make_season(
            self.creator,
            title="Code Season",
            skillworld="code",
        )
        code_season.is_published = True
        code_season.save()
        make_episode(
            self.creator,
            code_season,
            order=1,
            status=Episode.Status.PUBLISHED,
        )

        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons?skillworld=code")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(code_season.id))

    def test_list_seasons_unauthenticated_returns_403(self):
        from rest_framework.test import APIClient

        resp = APIClient().get(f"{BASE}/seasons")
        self.assertEqual(resp.status_code, 403)


class EpisodeAccessFieldsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.season.is_published = True
        self.season.save()
        self.paid_episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.PAID,
            title="Paid Episode",
        )
        self.free_episode = make_episode(
            self.creator,
            self.season,
            order=2,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
            title="Free Episode",
        )
        WalletService().credit_wallet(
            owner=self.user,
            amount=Decimal("100.00"),
            tx_type=SkillcoinTransaction.Type.ADMIN_ADJUSTMENT,
            description="Test credit",
            admin_user=self.creator,
        )

    def test_paid_episode_locked_before_purchase(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        paid = next(
            ep for ep in resp.data["data"] if ep["id"] == str(self.paid_episode.id)
        )
        self.assertEqual(
            paid["skillcoin_price"],
            str(SystemFinancialConfig.get_config().episode_purchase_price_skillcoins),
        )
        self.assertFalse(paid["is_purchased"])
        self.assertTrue(paid["is_locked"])

    def test_skillcoin_price_follows_platform_config(self):
        config = SystemFinancialConfig.get_config()
        config.episode_purchase_price_skillcoins = Decimal("30.00")
        config.save()
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        paid = next(
            ep for ep in resp.data["data"] if ep["id"] == str(self.paid_episode.id)
        )
        self.assertEqual(paid["skillcoin_price"], "30.00")

    def test_paid_episode_unlocked_after_purchase(self):
        ContentService().purchase_episode(self.user, str(self.paid_episode.id))
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        paid = next(
            ep for ep in resp.data["data"] if ep["id"] == str(self.paid_episode.id)
        )
        self.assertTrue(paid["is_purchased"])
        self.assertFalse(paid["is_locked"])

    def test_free_episode_access_fields(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        free = next(
            ep for ep in resp.data["data"] if ep["id"] == str(self.free_episode.id)
        )
        self.assertIsNone(free["skillcoin_price"])
        self.assertFalse(free["is_purchased"])
        self.assertFalse(free["is_locked"])
