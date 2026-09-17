"""Learner GET episode by ID with access control."""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.content import Episode
from skiflux.models.wallet import SkillcoinTransaction, SystemFinancialConfig
from skiflux.services.content_service import ContentService
from skiflux.services.wallet_service import WalletService

from .conftest import (
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class GetEpisodeDetailTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.season.is_published = True
        self.season.save()
        self.free_episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
            title="Free Episode",
        )
        self.paid_episode = make_episode(
            self.creator,
            self.season,
            order=2,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.PAID,
            title="Paid Episode",
        )
        WalletService().credit_wallet(
            owner=self.user,
            amount=Decimal("100.00"),
            tx_type=SkillcoinTransaction.Type.ADMIN_ADJUSTMENT,
            description="Test credit",
            admin_user=self.creator,
        )

    def test_get_free_episode_success(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/{self.free_episode.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["id"], str(self.free_episode.id))
        self.assertFalse(data["is_locked"])

    def test_get_paid_episode_locked_returns_403(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/{self.paid_episode.id}")
        self.assertEqual(resp.status_code, 403)

    def test_get_paid_episode_after_purchase_success(self):
        ContentService().purchase_episode(self.user, str(self.paid_episode.id))
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/{self.paid_episode.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertTrue(data["is_purchased"])
        self.assertFalse(data["is_locked"])
        self.assertEqual(
            data["skillcoin_price"],
            str(SystemFinancialConfig.get_config().episode_purchase_price_skillcoins),
        )

    def test_get_unpublished_episode_returns_404(self):
        draft = make_episode(
            self.creator,
            self.season,
            order=3,
            status=Episode.Status.DRAFT,
            access_type=Episode.AccessType.FREE,
        )
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/{draft.id}")
        self.assertEqual(resp.status_code, 404)

    def test_get_episode_unpublished_season_returns_404(self):
        hidden_season = make_season(self.creator, title="Hidden")
        ep = make_episode(
            self.creator,
            hidden_season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/{ep.id}")
        self.assertEqual(resp.status_code, 404)

    def test_get_episode_unauthenticated_returns_403(self):
        from rest_framework.test import APIClient

        resp = APIClient().get(f"{BASE}/episodes/{self.free_episode.id}")
        self.assertEqual(resp.status_code, 403)
