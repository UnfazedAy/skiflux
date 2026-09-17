"""
Admin Creator Management Tests
Covers: listing creators (HasCreatorViewPermission),
        creator oversight, episode override/unpublish (HasCreatorManagePermission).
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from skiflux.models import AdminUser
from skiflux.models.content import (
    Episode,
    EpisodePurchase,
    EpisodeRating,
    EpisodeView,
    Follow,
)
from skiflux.models.role import Permission

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


class CreatorListTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()

    def test_super_admin_can_list_creators(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_with_creator_view_can_list_creators(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="viewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],  # Wrong permission
            email="noperm@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/")
        self.assertEqual(resp.status_code, 403)


class CreatorAnalyticsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        # episodes
        self.ep1 = make_episode(
            self.creator,
            self.season,
            title="Analytics Ep 1",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.ep2 = make_episode(
            self.creator,
            self.season,
            title="Analytics Ep 2",
            order=2,
            status=Episode.Status.DRAFT,
        )

        # followers
        f1 = make_verified_user(email="f1@example.com")
        f2 = make_verified_user(email="f2@example.com")
        Follow.objects.create(follower=f1, creator=self.creator)
        Follow.objects.create(follower=f2, creator=self.creator)

        # purchases
        puser = make_verified_user(email="p1@example.com")
        EpisodePurchase.objects.create(user=puser, episode=self.ep1, amount_paid="5.00")

        # ratings
        r1 = make_verified_user(email="r1@example.com")
        r2 = make_verified_user(email="r2@example.com")
        EpisodeRating.objects.create(episode=self.ep1, user=r1, score=5)
        EpisodeRating.objects.create(episode=self.ep1, user=r2, score=3)

    def test_analytics_returns_expected_metrics(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/analytics/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        # data is returned directly in 'data' (not nested in results)
        self.assertEqual(data["total_episodes"], 2)
        self.assertEqual(data["total_followers"], 2)
        self.assertEqual(Decimal(str(data["total_earnings"])), Decimal("5.00"))
        self.assertEqual(Decimal(str(data["avg_rating"])), Decimal("4.0"))
        self.assertEqual(data["total_ratings"], 2)


class CreatorEpisodesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        # create several episodes with varying statuses
        self.ep_pub = make_episode(
            self.creator,
            self.season,
            title="Pub Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.ep_draft = make_episode(
            self.creator,
            self.season,
            title="Draft Ep",
            order=2,
            status=Episode.Status.DRAFT,
        )
        # more to test pagination handling
        for i in range(3, 6):
            make_episode(self.creator, self.season, title=f"Ep {i}", order=i)

    def test_creator_episodes_returns_paginated_results(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/episodes/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 5)
        self.assertIsNone(payload["next"])
        self.assertIsNone(payload["previous"])
        self.assertIsInstance(payload["results"], list)
        self.assertEqual(len(payload["results"]), 5)

    def test_creator_episodes_can_filter_by_status(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/episodes/?status=published"
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 4)
        self.assertEqual(len(payload["results"]), 4)

    def test_creator_episodes_uses_limit_query_param(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/episodes/?limit=2")
        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 5)
        self.assertIsNotNone(payload["next"])
        self.assertIsNone(payload["previous"])
        self.assertEqual(len(payload["results"]), 2)

    def test_unauthenticated_cannot_list_creators(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/creators/")
        self.assertEqual(resp.status_code, 403)

    def test_user_token_rejected_on_creator_list(self):
        from skiflux.models import User
        from skiflux.utils.auth import create_access_token

        user = User.objects.create_user(
            email="user@example.com",
            first_name="U",
            password="StrongPass1!",
        )
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(str(user.id))}"
        )
        resp = client.get(f"{BASE}/admin/creators/")
        self.assertEqual(resp.status_code, 403)


class CreatorDirectoryStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator(
            email="directory-one@skiflux.com",
            username="directoryone",
        )
        self.second_creator = make_creator(
            email="directory-two@skiflux.com",
            username="directorytwo",
        )
        now = timezone.now()
        self.creator.last_login = now
        self.creator.save(update_fields=["last_login"])

        self.season = make_season(self.creator, title="Directory Season")
        self.second_season = make_season(
            self.second_creator,
            title="Second Directory Season",
        )
        make_episode(self.creator, self.season, title="Directory Ep 1", order=1)
        make_episode(self.creator, self.season, title="Directory Ep 2", order=2)
        make_episode(
            self.second_creator,
            self.second_season,
            title="Directory Ep 3",
            order=1,
        )

    def test_directory_stats_returns_expected_metrics(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/directory/stats/")

        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["total_creators"], 2)
        self.assertEqual(data["active_today"], 1)
        self.assertEqual(data["new_this_week"], 2)
        self.assertEqual(
            Decimal(str(data["avg_uploads_per_creator_this_week"])),
            Decimal("1.5"),
        )

    def test_directory_stats_uses_cached_value(self):
        cache.set(
            "creator_directory_stats",
            {
                "total_creators": 42,
                "new_creators_this_month": 7,
                "growth_percentage_this_month": 16.7,
                "active_today": 7,
                "new_this_week": 3,
                "avg_uploads_per_creator_this_week": Decimal("2.5"),
                "pending_submissions": 5,
                "avg_sla_rate": Decimal("4.5"),
            },
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/directory/stats/")

        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["total_creators"], 42)
        self.assertEqual(data["new_creators_this_month"], 7)
        self.assertEqual(
            Decimal(str(data["growth_percentage_this_month"])), Decimal("16.7")
        )
        self.assertEqual(data["active_today"], 7)
        self.assertEqual(data["new_this_week"], 3)
        self.assertEqual(
            Decimal(str(data["avg_uploads_per_creator_this_week"])),
            Decimal("2.5"),
        )
        self.assertEqual(data["pending_submissions"], 5)
        self.assertEqual(Decimal(str(data["avg_sla_rate"])), Decimal("4.5"))

    def test_admin_with_creator_view_can_get_directory_stats(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="directorystatsviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/directory/stats/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked_from_directory_stats(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="directorystatsblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/directory/stats/")
        self.assertEqual(resp.status_code, 403)


class CreatorDirectoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator(
            email="ada.creator@skiflux.com",
            username="adastreams",
        )
        self.creator.first_name = "Ada"
        self.creator.last_name = "Streams"
        self.creator.save(update_fields=["first_name", "last_name"])

        self.suspended_creator = make_creator(
            email="ben.creator@skiflux.com",
            username="benbuilds",
        )
        self.suspended_creator.first_name = "Ben"
        self.suspended_creator.last_name = "Builds"
        self.suspended_creator.status = AdminUser.Status.SUSPENDED
        self.suspended_creator.save(update_fields=["first_name", "last_name", "status"])

        self.season = make_season(self.creator, title="Directory List Season")
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Paid Directory Ep",
            order=1,
        )
        buyer = make_verified_user(email="directorybuyer@example.com")
        EpisodePurchase.objects.create(
            user=buyer,
            episode=self.episode,
            amount_paid="9.99",
        )

    def test_directory_returns_paginated_creator_rows_with_annotations(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/directory/")

        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 2)
        self.assertIsNone(payload["next"])
        self.assertIsNone(payload["previous"])
        self.assertEqual(len(payload["results"]), 2)

        row = next(
            item for item in payload["results"] if item["id"] == str(self.creator.id)
        )
        self.assertEqual(row["first_name"], "Ada")
        self.assertEqual(row["last_name"], "Streams")
        self.assertEqual(row["username"], "adastreams")
        self.assertEqual(row["email"], "ada.creator@skiflux.com")
        self.assertEqual(row["episode_count"], 1)
        self.assertEqual(Decimal(str(row["earnings"])), Decimal("9.99"))
        self.assertEqual(row["status"], AdminUser.Status.ACTIVE)

    def test_directory_can_filter_by_search(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/directory/?search=ada")

        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["username"], "adastreams")

    def test_directory_can_filter_by_status(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/directory/?status={AdminUser.Status.SUSPENDED}"
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["username"], "benbuilds")

    def test_directory_can_filter_by_created_date_range(self):
        old_date = timezone.now() - timedelta(days=14)
        AdminUser.objects.filter(id=self.suspended_creator.id).update(
            created_at=old_date
        )
        today = timezone.localdate().isoformat()

        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/directory/?date_from={today}&date_to={today}"
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["username"], "adastreams")

    def test_directory_rejects_invalid_date_range(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/directory/?date_from=2026-05-22&date_to=2026-05-21"
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_with_creator_view_can_get_directory(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="directoryviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/directory/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked_from_directory(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="directoryblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/directory/")
        self.assertEqual(resp.status_code, 403)


class CreatorOversightTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        make_episode(
            self.creator,
            self.season,
            title="Ep 1",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        make_episode(
            self.creator,
            self.season,
            title="Ep 2",
            order=2,
            status=Episode.Status.DRAFT,
        )

    def test_super_admin_can_view_creator_oversight(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/oversight/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("episodes_count", resp.data["data"])
        self.assertEqual(resp.data["data"]["episodes_count"], 2)

    def test_oversight_returns_episode_status(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/oversight/")
        episodes = resp.data["data"]["episodes"]
        statuses = {e["status"] for e in episodes}
        self.assertIn("published", statuses)
        self.assertIn("draft", statuses)

    def test_admin_with_creator_view_can_see_oversight(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="vieweradmin@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/oversight/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_permission_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="noperm2@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/oversight/")
        self.assertEqual(resp.status_code, 403)

    def test_oversight_for_nonexistent_creator_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{uuid.uuid4()}/oversight/")
        self.assertEqual(resp.status_code, 400)


class CreatorProfileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.creator.last_name = "Profile"
        self.creator.bio = "Building useful design lessons."
        self.creator.save(update_fields=["last_name", "bio"])
        self.season = make_season(self.creator)
        make_episode(
            self.creator,
            self.season,
            title="Published Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        make_episode(
            self.creator,
            self.season,
            title="Draft Ep",
            order=2,
            status=Episode.Status.DRAFT,
        )

    def test_super_admin_can_view_creator_profile(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/profile/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["id"], str(self.creator.id))
        self.assertEqual(resp.data["data"]["email"], self.creator.email)
        self.assertEqual(resp.data["data"]["username"], self.creator.username)
        self.assertEqual(resp.data["data"]["bio"], self.creator.bio)
        self.assertEqual(resp.data["data"]["display_name"], self.creator.display_name)

    def test_creator_profile_returns_summary_stats(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/profile/")

        stats = resp.data["data"]["stats"]
        self.assertEqual(stats["seasons_count"], 1)
        self.assertEqual(stats["episodes_count"], 2)
        self.assertEqual(stats["subscribers_count"], 0)
        self.assertEqual(stats["submissions_count"], 0)
        self.assertEqual(stats["sla_avg"], 0)

    def test_admin_with_creator_view_can_view_creator_profile(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="profileviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/profile/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked_from_profile(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="profileblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/profile/")
        self.assertEqual(resp.status_code, 403)

    def test_profile_for_non_creator_admin_returns_400(self):
        admin = AdminUser.objects.create_admin(
            email="plainadmin@skiflux.com",
            first_name="Plain",
            password="AdminPass1!",
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{admin.id}/profile/")
        self.assertEqual(resp.status_code, 400)

    def test_profile_for_nonexistent_creator_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{uuid.uuid4()}/profile/")
        self.assertEqual(resp.status_code, 400)


class EpisodeOverrideTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Override Target",
            order=1,
            status=Episode.Status.PUBLISHED,
        )

    def test_super_admin_can_unpublish_episode(self):
        client = admin_auth_client(self.super_admin)
        resp = client.patch(
            f"{BASE}/admin/creators/{self.creator.id}/override/",
            {
                "episode_id": str(self.episode.id),
                "action": "unpublish",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.status, Episode.Status.DRAFT)

    def test_admin_with_creator_manage_can_override(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_MANAGE],
            email="manager@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.patch(
            f"{BASE}/admin/creators/{self.creator.id}/override/",
            {
                "episode_id": str(self.episode.id),
                "action": "unpublish",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_with_only_view_cannot_override(self):
        """CREATOR_VIEW is not enough for override — must have CREATOR_MANAGE."""
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="viewonly@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.patch(
            f"{BASE}/admin/creators/{self.creator.id}/override/",
            {
                "episode_id": str(self.episode.id),
                "action": "unpublish",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_override_with_invalid_action_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.patch(
            f"{BASE}/admin/creators/{self.creator.id}/override/",
            {
                "episode_id": str(self.episode.id),
                "action": "delete",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_override_with_nonexistent_episode_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.patch(
            f"{BASE}/admin/creators/{self.creator.id}/override/",
            {
                "episode_id": str(uuid.uuid4()),
                "action": "unpublish",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unauthenticated_cannot_override_episode(self):
        client = APIClient()
        resp = client.patch(
            f"{BASE}/admin/creators/{self.creator.id}/override/",
            {
                "episode_id": str(self.episode.id),
                "action": "unpublish",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class CreatorLeaderboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

        self.creator_a = make_creator(
            email="leaderboard-a@skiflux.com",
            username="leaderboarda",
        )
        self.creator_b = make_creator(
            email="leaderboard-b@skiflux.com",
            username="leaderboardb",
        )
        self.season_a = make_season(self.creator_a, title="Leaderboard Season A")
        self.season_b = make_season(self.creator_b, title="Leaderboard Season B")

        # creator_a gets 3 episodes, creator_b gets 1 — so a ranks higher
        for i in range(1, 4):
            make_episode(self.creator_a, self.season_a, title=f"A Ep {i}", order=i)
        make_episode(self.creator_b, self.season_b, title="B Ep 1", order=1)

    def test_super_admin_can_get_leaderboard(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard")
        self.assertEqual(resp.status_code, 200)

    def test_leaderboard_ordered_by_episode_count_descending(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard")
        results = resp.data["data"]
        self.assertEqual(results[0]["username"], "leaderboarda")
        self.assertEqual(results[0]["episodes_count"], 3)
        self.assertEqual(results[0]["rank"], 1)
        self.assertEqual(results[1]["username"], "leaderboardb")
        self.assertEqual(results[1]["episodes_count"], 1)
        self.assertEqual(results[1]["rank"], 2)

    def test_leaderboard_respects_limit_query_param(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard?limit=1")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["rank"], 1)

    def test_leaderboard_clamps_invalid_limit(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard?limit=abc")
        self.assertEqual(resp.status_code, 200)  # falls back to default 10

    def test_leaderboard_trend_is_zero_when_no_growth_this_month(self):
        # backdating all episodes to last month means no new episodes this month
        from django.utils import timezone

        last_month = timezone.now() - timedelta(days=40)
        Episode.objects.filter(creator=self.creator_a).update(created_at=last_month)

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard")
        results = resp.data["data"]
        a_row = next(r for r in results if r["username"] == "leaderboarda")
        self.assertEqual(
            Decimal(str(a_row["episodes_count_trend_percentage"])), Decimal("0.0")
        )

    def test_leaderboard_trend_is_100_when_all_episodes_are_new(self):
        # creator_b has only 1 episode created this month no prior history
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard")
        results = resp.data["data"]
        b_row = next(r for r in results if r["username"] == "leaderboardb")
        self.assertEqual(
            Decimal(str(b_row["episodes_count_trend_percentage"])), Decimal("100.0")
        )

    def test_admin_with_creator_view_can_get_leaderboard(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="leaderboardviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="leaderboardblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/creators/leaderboard")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_cannot_get_leaderboard(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/creators/leaderboard")
        self.assertEqual(resp.status_code, 403)


class CreatorAudienceDistributionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()

        # viewers with countries
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Audience Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )

        us1 = make_verified_user(email="us1@example.com")
        us2 = make_verified_user(email="us2@example.com")
        ng1 = make_verified_user(email="ng1@example.com")
        no_country = make_verified_user(email="nocountry@example.com")

        from skiflux.models import User

        User.objects.filter(id=us1.id).update(country="US")
        User.objects.filter(id=us2.id).update(country="US")
        User.objects.filter(id=ng1.id).update(country="NG")

        EpisodeView.objects.create(user=us1, episode=self.episode)
        EpisodeView.objects.create(user=us2, episode=self.episode)
        EpisodeView.objects.create(user=ng1, episode=self.episode)
        EpisodeView.objects.create(user=no_country, episode=self.episode)

    def test_super_admin_can_get_audience_distribution(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/audience-distribution"
        )
        self.assertEqual(resp.status_code, 200)

    def test_audience_distribution_returns_correct_percentages(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/audience-distribution"
        )
        data = resp.data["data"]
        countries = {row["country"]: row["pct"] for row in data}

        # 2 out of 3 viewers with country are US → 67%
        self.assertIn("US", countries)
        self.assertIn("NG", countries)
        self.assertEqual(countries["US"], 67)
        self.assertEqual(countries["NG"], 33)

    def test_audience_excludes_users_without_country(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/audience-distribution"
        )
        data = resp.data["data"]
        countries = [row["country"] for row in data]
        self.assertNotIn("", countries)
        self.assertNotIn(None, countries)

    def test_audience_distribution_respects_limit_param(self):
        # add more countries
        season = make_season(self.creator)
        ep = make_episode(
            self.creator,
            season,
            title="Limit Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        from skiflux.models import User

        for i, code in enumerate(["GB", "DE", "FR", "CA"]):
            u = make_verified_user(email=f"{code.lower()}@example.com")
            User.objects.filter(id=u.id).update(country=code)
            EpisodeView.objects.create(user=u, episode=ep)

        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/audience-distribution?limit=2"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]), 2)

    def test_audience_distribution_returns_empty_for_creator_with_no_views(self):
        new_creator = make_creator(
            email="noviews@skiflux.com",
            username="noviews",
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{new_creator.id}/analytics/audience-distribution"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"], [])

    def test_admin_with_creator_view_can_get_audience(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="audienceviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/audience-distribution"
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="audienceblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/audience-distribution"
        )
        self.assertEqual(resp.status_code, 403)

    def test_nonexistent_creator_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{uuid.uuid4()}/analytics/audience-distribution"
        )
        self.assertEqual(resp.status_code, 404)


class CreatorRevenueGrowthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Revenue Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        buyer1 = make_verified_user(email="buyer1@example.com")
        buyer2 = make_verified_user(email="buyer2@example.com")
        EpisodePurchase.objects.create(
            user=buyer1,
            episode=self.episode,
            amount_paid="20.00",
            status=EpisodePurchase.Status.ACTIVE,
        )
        EpisodePurchase.objects.create(
            user=buyer2,
            episode=self.episode,
            amount_paid="15.00",
            status=EpisodePurchase.Status.ACTIVE,
        )

    def test_super_admin_can_get_revenue_growth(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=week"
        )
        self.assertEqual(resp.status_code, 200)

    def test_revenue_response_has_correct_shape(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=week"
        )
        data = resp.data["data"]
        self.assertIn("labels", data)
        self.assertIn("current", data)
        self.assertIn("previous", data)
        self.assertEqual(len(data["labels"]), len(data["current"]))
        self.assertEqual(len(data["labels"]), len(data["previous"]))

    def test_revenue_current_period_includes_purchases(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=week"
        )
        data = resp.data["data"]
        self.assertGreater(sum(data["current"]), 0)

    def test_revenue_excludes_refunded_purchases(self):
        refunded_user = make_verified_user(email="refunded@example.com")
        ep2 = make_episode(
            self.creator,
            self.season,
            title="Refunded Ep",
            order=2,
            status=Episode.Status.PUBLISHED,
        )
        EpisodePurchase.objects.create(
            user=refunded_user,
            episode=ep2,
            amount_paid="50.00",
            status=EpisodePurchase.Status.REFUNDED,
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=week"
        )
        data = resp.data["data"]
        # total current should be 35.00 not 85.00
        self.assertAlmostEqual(sum(data["current"]), 35.0)

    def test_revenue_defaults_to_week_period(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/")
        self.assertEqual(resp.status_code, 200)

    def test_revenue_month_period_returns_200(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=month"
        )
        self.assertEqual(resp.status_code, 200)

    def test_revenue_year_period_returns_200(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=year"
        )
        self.assertEqual(resp.status_code, 200)

    def test_invalid_period_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=daily"
        )
        self.assertEqual(resp.status_code, 400)

    def test_revenue_returns_empty_for_creator_with_no_purchases(self):
        new_creator = make_creator(
            email="nopurchases@skiflux.com",
            username="nopurchases",
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{new_creator.id}/analytics/revenue/?period=week"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["labels"], [])
        self.assertEqual(data["current"], [])
        self.assertEqual(data["previous"], [])

    def test_admin_with_creator_view_can_get_revenue(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="revenueviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=week"
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="revenueblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/revenue/?period=week"
        )
        self.assertEqual(resp.status_code, 403)

    def test_nonexistent_creator_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{uuid.uuid4()}/analytics/revenue/?period=week"
        )
        self.assertEqual(resp.status_code, 404)


class CreatorSeasonsPerformanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()

        self.season1 = make_season(self.creator, title="Season One")
        self.season2 = make_season(self.creator, title="Season Two")

        self.ep1 = make_episode(
            self.creator,
            self.season1,
            title="S1 Ep1",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.ep2 = make_episode(
            self.creator,
            self.season2,
            title="S2 Ep1",
            order=1,
            status=Episode.Status.PUBLISHED,
        )

        buyer = make_verified_user(email="seasonbuyer@example.com")
        EpisodePurchase.objects.create(
            user=buyer,
            episode=self.ep1,
            amount_paid="10.00",
            status=EpisodePurchase.Status.ACTIVE,
        )

        viewer = make_verified_user(email="seasonviewer@example.com")
        EpisodeView.objects.create(user=viewer, episode=self.ep1, completed=True)

        rater = make_verified_user(email="seasonrater@example.com")
        EpisodeRating.objects.create(episode=self.ep1, user=rater, score=4)

    def test_super_admin_can_get_seasons_performance(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        self.assertEqual(resp.status_code, 200)

    def test_seasons_performance_returns_paginated_results(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        payload = resp.data["data"]
        self.assertIn("count", payload)
        self.assertIn("results", payload)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["results"]), 2)

    def test_seasons_performance_correct_sales_and_revenue(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        results = resp.data["data"]["results"]
        s1 = next(r for r in results if r["title"] == "Season One")
        self.assertEqual(s1["total_sales"], 1)
        self.assertAlmostEqual(float(s1["revenue"]), 10.0)

    def test_seasons_performance_correct_completion_percentage(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        results = resp.data["data"]["results"]
        s1 = next(r for r in results if r["title"] == "Season One")
        # 1 completed out of 1 viewer = 100%
        self.assertEqual(s1["completion_percentage"], 100)

    def test_seasons_performance_correct_avg_rating(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        results = resp.data["data"]["results"]
        s1 = next(r for r in results if r["title"] == "Season One")
        self.assertEqual(s1["avg_rating"], 4.0)

    def test_season_with_no_activity_returns_zero_values(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        results = resp.data["data"]["results"]
        s2 = next(r for r in results if r["title"] == "Season Two")
        self.assertEqual(s2["total_sales"], 0)
        self.assertAlmostEqual(float(s2["revenue"]), 0.0)
        self.assertEqual(s2["completion_percentage"], 0)
        self.assertIsNone(s2["avg_rating"])

    def test_seasons_performance_returns_empty_for_creator_with_no_seasons(self):
        new_creator = make_creator(
            email="noseasons@skiflux.com",
            username="noseasons",
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{new_creator.id}/analytics/seasons-performance/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 0)
        self.assertEqual(resp.data["data"]["results"], [])

    def test_admin_with_creator_view_can_get_seasons_performance(self):
        admin, _ = make_admin_with_role(
            [Permission.CREATOR_VIEW],
            email="seasonsviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_creator_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="seasonsblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/creators/{self.creator.id}/analytics/seasons-performance/"
        )
        self.assertEqual(resp.status_code, 403)

    def test_nonexistent_creator_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/creators/{uuid.uuid4()}/analytics/seasons-performance/"
        )
        self.assertEqual(resp.status_code, 404)
