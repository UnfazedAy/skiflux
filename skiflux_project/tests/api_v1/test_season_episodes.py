"""
Public Season Episodes Tests
Tests for the public endpoint to retrieve published episodes in a season.
Endpoint: GET /api/v1/seasons/{season_id}/episodes
"""

import uuid

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.content import Episode

from .conftest import (
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class GetSeasonEpisodesTests(TestCase):
    """Test public endpoint for retrieving episodes in a season."""

    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.season.is_published = True
        self.season.save()
        # Create multiple episodes with different statuses
        self.published_ep1 = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            title="Published Episode 1",
        )
        self.published_ep2 = make_episode(
            self.creator,
            self.season,
            order=2,
            status=Episode.Status.PUBLISHED,
            title="Published Episode 2",
        )
        self.draft_ep = make_episode(
            self.creator,
            self.season,
            order=3,
            status=Episode.Status.DRAFT,
            title="Draft Episode",
        )
        self.review_ep = make_episode(
            self.creator,
            self.season,
            order=4,
            status=Episode.Status.REVIEW,
            title="Review Episode",
        )

    def test_get_season_episodes_authenticated_user(self):
        """Test authenticated user can retrieve published episodes."""
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)

    def test_get_season_episodes_only_published(self):
        """Test only published episodes are returned."""
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        episodes = resp.data["data"]
        # Should only have 2 published episodes
        self.assertEqual(len(episodes), 2)
        # Verify all returned episodes are published
        for episode in episodes:
            self.assertEqual(episode["status"], "published")
        # Verify correct episodes are returned
        ids = [ep["id"] for ep in episodes]
        self.assertIn(str(self.published_ep1.id), ids)
        self.assertIn(str(self.published_ep2.id), ids)
        self.assertNotIn(str(self.draft_ep.id), ids)
        self.assertNotIn(str(self.review_ep.id), ids)

    def test_get_season_episodes_ordered_by_order_field(self):
        """Test episodes are ordered by the order field."""
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        episodes = resp.data["data"]
        # Should be ordered by order field
        self.assertEqual(episodes[0]["order"], 1)
        self.assertEqual(episodes[1]["order"], 2)

    def test_get_season_episodes_response_structure(self):
        """Test response contains all expected episode fields."""
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        episodes = resp.data["data"]
        self.assertTrue(len(episodes) > 0)
        # Check first episode has expected fields
        episode = episodes[0]
        self.assertIn("id", episode)
        self.assertIn("title", episode)
        self.assertIn("description", episode)
        self.assertIn("status", episode)
        self.assertIn("order", episode)
        self.assertIn("access_type", episode)
        self.assertIn("skillcoin_price", episode)
        self.assertIn("is_purchased", episode)
        self.assertIn("is_locked", episode)
        self.assertIn("created_at", episode)

    def test_get_season_episodes_empty_season(self):
        """Unpublished empty season is not visible to learners."""
        empty_season = make_season(self.creator, title="Empty Season")
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{empty_season.id}/episodes")
        self.assertEqual(resp.status_code, 404)

    def test_get_season_episodes_only_draft_episodes(self):
        """Unpublished season with only draft episodes is not visible."""
        draft_season = make_season(self.creator, title="Draft Season")
        make_episode(
            self.creator,
            draft_season,
            order=1,
            status=Episode.Status.DRAFT,
            title="Draft Only",
        )
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{draft_season.id}/episodes")
        self.assertEqual(resp.status_code, 404)

    def test_get_season_episodes_unpublished_season_returns_404(self):
        """Unpublished seasons are hidden from learners."""
        unpublished = make_season(self.creator, title="Hidden Season")
        make_episode(
            self.creator,
            unpublished,
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{unpublished.id}/episodes")
        self.assertEqual(resp.status_code, 404)

    def test_get_season_episodes_nonexistent_returns_404(self):
        """Test nonexistent season returns 404."""
        client = user_auth_client(self.user)
        fake_id = uuid.uuid4()
        resp = client.get(f"{BASE}/seasons/{fake_id}/episodes")
        self.assertEqual(resp.status_code, 404)

    def test_get_season_episodes_includes_episode_details(self):
        """Test response includes full episode details for serialization."""
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        episodes = resp.data["data"]
        episode = episodes[0]
        # Verify episode title matches
        self.assertIn(episode["title"], ["Published Episode 1", "Published Episode 2"])
        # Verify access_type is present
        self.assertIsNotNone(episode["access_type"])

    def test_get_season_episodes_multiple_seasons_isolation(self):
        """Test episodes are isolated by season."""
        # Create another season with published episodes
        other_season = make_season(self.creator, title="Other Season")
        other_season.is_published = True
        other_season.save()
        other_ep = make_episode(
            self.creator,
            other_season,
            order=1,
            status=Episode.Status.PUBLISHED,
            title="Other Season Episode",
        )
        client = user_auth_client(self.user)
        # Get episodes from first season
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        episodes = resp.data["data"]
        # Should only have 2 episodes from first season
        self.assertEqual(len(episodes), 2)
        ids = [ep["id"] for ep in episodes]
        # Should not include episode from other season
        self.assertNotIn(str(other_ep.id), ids)

    def test_get_season_episodes_access_type_free_and_paid(self):
        """Test both free and paid episodes are returned when published."""
        # Add a paid episode
        paid_ep = make_episode(
            self.creator,
            self.season,
            order=5,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.PAID,
            title="Paid Episode",
        )
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/seasons/{self.season.id}/episodes")
        self.assertEqual(resp.status_code, 200)
        episodes = resp.data["data"]
        # Should have 3 published episodes (2 original + 1 paid)
        self.assertEqual(len(episodes), 3)
        # Verify paid episode is included
        ids = [ep["id"] for ep in episodes]
        self.assertIn(str(paid_ep.id), ids)
        # Verify both access types are present
        access_types = [ep["access_type"] for ep in episodes]
        self.assertIn("free", access_types)
        self.assertIn("paid", access_types)
