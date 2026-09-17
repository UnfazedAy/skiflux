"""
Admin Episode Review Tests
Covers: verification stats, verification queue, bulk episode review.
"""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from skiflux.models.content import Episode
from skiflux.models.role import Permission

from .conftest import (
    admin_auth_client,
    anon_client,
    make_admin_with_role,
    make_creator,
    make_episode,
    make_season,
    make_super_admin,
)

BASE = "/api/v1"


class VerificationStatsTests(TestCase):
    """Tests for verification stats endpoint."""

    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

        # Create a creator
        self.creator = make_creator()

        # Create a season
        self.season = make_season(self.creator)

    def test_verification_stats_as_super_admin_success(self):
        """Super admin can retrieve verification stats."""
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/stats")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        self.assertIn("data", resp.data)

        # Stats should contain expected fields
        stats = resp.data["data"]
        self.assertIn("pending_count", stats)
        self.assertIn("pending_change_pct", stats)
        self.assertIn("avg_wait_secs", stats)
        self.assertIn("avg_response_time_minutes", stats)
        self.assertIn("sla_breach_count", stats)

    def test_verification_stats_with_pending_episodes(self):
        """Verification stats includes pending episode counts."""
        # Create episodes in REVIEW status
        for i in range(3):
            make_episode(
                self.creator,
                self.season,
                title=f"Episode {i + 1}",
                order=i + 1,
                status=Episode.Status.REVIEW,
            )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/stats")

        self.assertEqual(resp.status_code, 200)
        stats = resp.data["data"]
        self.assertGreaterEqual(stats["pending_count"], 3)

    def test_verification_stats_admin_with_permission_success(self):
        """Admin with CONTENT_MANAGE permission can access stats."""
        admin, role = make_admin_with_role([Permission.CONTENT_MANAGE])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/stats")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_verification_stats_admin_without_permission_returns_403(self):
        """Admin without CONTENT_MANAGE permission gets 403."""
        admin, role = make_admin_with_role([])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/stats")

        self.assertEqual(resp.status_code, 403)

    def test_verification_stats_unauthenticated_returns_403(self):
        """Unauthenticated request returns 403."""
        client = anon_client()
        resp = client.get(f"{BASE}/admin/content/episodes/verification/stats")

        self.assertEqual(resp.status_code, 403)


class VerificationQueueTests(TestCase):
    """Tests for verification queue endpoint."""

    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

        # Create multiple creators and seasons
        self.creators = []
        self.seasons = []
        self.episodes = []

        for i in range(2):
            creator = make_creator(
                email=f"creator{i}@skiflux.com",
                username=f"creator{i}",
            )
            self.creators.append(creator)

            season = make_season(creator, title=f"Season {i}")
            self.seasons.append(season)

    def test_verification_queue_success(self):
        """Retrieve verification queue successfully."""
        # Create episodes in REVIEW status
        for i, creator in enumerate(self.creators):
            for j in range(2):
                make_episode(
                    creator,
                    self.seasons[i],
                    title=f"Episode {j + 1}",
                    order=j + 1,
                    status=Episode.Status.REVIEW,
                )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/queue")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        self.assertIn("data", resp.data)

        # Check pagination structure
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)

    def test_verification_queue_filter_by_priority(self):
        """Filter verification queue by priority."""
        # Create episodes
        ep1 = make_episode(
            self.creators[0],
            self.seasons[0],
            title="Episode 1",
            order=1,
            status=Episode.Status.REVIEW,
        )
        ep1.submitted_for_review_at = timezone.now() - timedelta(days=5)
        ep1.save()

        ep2 = make_episode(
            self.creators[1],
            self.seasons[1],
            title="Episode 2",
            order=1,
            status=Episode.Status.REVIEW,
        )
        ep2.submitted_for_review_at = timezone.now()
        ep2.save()

        client = admin_auth_client(self.super_admin)

        # Test filtering by high priority (older submissions)
        resp = client.get(
            f"{BASE}/admin/content/episodes/verification/queue?priority=high"
        )
        self.assertEqual(resp.status_code, 200)

    def test_verification_queue_filter_by_ordering(self):
        """Filter verification queue by ordering (oldest/newest)."""
        # Create episodes at different times
        ep1 = make_episode(
            self.creators[0],
            self.seasons[0],
            title="Episode 1",
            order=1,
            status=Episode.Status.REVIEW,
        )
        ep1.submitted_for_review_at = timezone.now() - timedelta(days=5)
        ep1.save()

        client = admin_auth_client(self.super_admin)

        # Test oldest ordering
        resp = client.get(
            f"{BASE}/admin/content/episodes/verification/queue?ordering=oldest"
        )
        self.assertEqual(resp.status_code, 200)

        # Test newest ordering
        resp = client.get(
            f"{BASE}/admin/content/episodes/verification/queue?ordering=newest"
        )
        self.assertEqual(resp.status_code, 200)

    def test_verification_queue_includes_episode_details(self):
        """Verification queue includes required episode details."""
        make_episode(
            self.creators[0],
            self.seasons[0],
            title="Test Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/queue")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        if results:
            episode = results[0]
            self.assertIn("id", episode)
            self.assertIn("title", episode)
            self.assertIn("season_skillworld", episode)
            self.assertIn("creator_name", episode)
            self.assertIn("submitted_at", episode)
            self.assertIn("sla_deadline", episode)
            self.assertIn("sla_breached", episode)
            self.assertIn("priority", episode)
            self.assertIn("status", episode)

    def test_verification_queue_invalid_filter_returns_400(self):
        """Invalid filter parameter returns 400."""
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/content/episodes/verification/queue?priority=invalid"
        )

        self.assertEqual(resp.status_code, 400)

    def test_verification_queue_admin_without_permission_returns_403(self):
        """Admin without CONTENT_MANAGE permission gets 403."""
        admin, role = make_admin_with_role([])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/queue")

        self.assertEqual(resp.status_code, 403)

    def test_verification_queue_unauthenticated_returns_403(self):
        """Unauthenticated request returns 403."""
        client = anon_client()
        resp = client.get(f"{BASE}/admin/content/episodes/verification/queue")

        self.assertEqual(resp.status_code, 403)

    def test_verification_queue_excludes_non_review_episodes(self):
        """Queue only includes episodes in REVIEW status."""
        # Create episodes in various statuses
        make_episode(
            self.creators[0],
            self.seasons[0],
            title="Published",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        make_episode(
            self.creators[0],
            self.seasons[0],
            title="Draft",
            order=2,
            status=Episode.Status.DRAFT,
        )
        make_episode(
            self.creators[0],
            self.seasons[0],
            title="Under Review",
            order=3,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/episodes/verification/queue")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        # All returned episodes should be in REVIEW status
        for episode in results:
            self.assertEqual(episode["status"], Episode.Status.REVIEW)


class BulkReviewEpisodesTests(TestCase):
    """Tests for bulk review episodes endpoint."""

    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

        # Create creator and season
        self.creator = make_creator()
        self.season = make_season(self.creator)

    def test_bulk_approve_episodes_success(self):
        """Bulk approve episodes successfully."""
        # Create episodes in REVIEW status
        episodes = []
        for i in range(3):
            ep = make_episode(
                self.creator,
                self.season,
                title=f"Episode {i + 1}",
                order=i + 1,
                status=Episode.Status.REVIEW,
            )
            episodes.append(ep)

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id) for ep in episodes],
                "action": "approve",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

        # Verify episodes are now published
        for ep in episodes:
            ep.refresh_from_db()
            self.assertEqual(ep.status, Episode.Status.PUBLISHED)
            self.assertIsNotNone(ep.reviewed_by)
            self.assertIsNotNone(ep.reviewed_at)

    def test_bulk_reject_episodes_with_reason_success(self):
        """Bulk reject episodes with rejection reason."""
        # Create episodes in REVIEW status
        episodes = []
        for i in range(2):
            ep = make_episode(
                self.creator,
                self.season,
                title=f"Episode {i + 1}",
                order=i + 1,
                status=Episode.Status.REVIEW,
            )
            episodes.append(ep)

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id) for ep in episodes],
                "action": "reject",
                "reason": "Content policy violation",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

        # Verify episodes are now rejected
        for ep in episodes:
            ep.refresh_from_db()
            self.assertEqual(ep.status, Episode.Status.REJECTED)
            self.assertEqual(ep.rejection_reason, "Content policy violation")
            self.assertEqual(ep.reviewed_by, self.super_admin)

    def test_bulk_reject_without_reason_returns_400(self):
        """Bulk reject without reason returns 400."""
        ep = make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id)],
                "action": "reject",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_bulk_review_empty_episode_ids_returns_400(self):
        """Empty episode_ids list returns 400."""
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [],
                "action": "approve",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_bulk_review_missing_action_returns_400(self):
        """Missing action returns 400."""
        ep = make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id)],
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_bulk_review_invalid_action_returns_400(self):
        """Invalid action returns 400."""
        ep = make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id)],
                "action": "invalid",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_bulk_review_skips_non_review_episodes(self):
        """Bulk review skips episodes not in REVIEW status."""
        # Create episodes in different statuses
        review_ep = make_episode(
            self.creator,
            self.season,
            title="Review",
            order=1,
            status=Episode.Status.REVIEW,
        )
        published_ep = make_episode(
            self.creator,
            self.season,
            title="Published",
            order=2,
            status=Episode.Status.PUBLISHED,
        )
        draft_ep = make_episode(
            self.creator,
            self.season,
            title="Draft",
            order=3,
            status=Episode.Status.DRAFT,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [
                    str(review_ep.id),
                    str(published_ep.id),
                    str(draft_ep.id),
                ],
                "action": "approve",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)

        # Only review_ep should be processed
        data = resp.data["data"]
        self.assertEqual(len(data["processed"]), 1)
        self.assertEqual(len(data["skipped"]), 2)

        # Verify status changes
        review_ep.refresh_from_db()
        self.assertEqual(review_ep.status, Episode.Status.PUBLISHED)

        published_ep.refresh_from_db()
        self.assertEqual(published_ep.status, Episode.Status.PUBLISHED)

        draft_ep.refresh_from_db()
        self.assertEqual(draft_ep.status, Episode.Status.DRAFT)

    def test_bulk_review_nonexistent_episodes(self):
        """Bulk review with nonexistent episode IDs."""
        import uuid

        ep = make_episode(
            self.creator,
            self.season,
            title="Real",
            order=1,
            status=Episode.Status.REVIEW,
        )
        fake_id = str(uuid.uuid4())

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id), fake_id],
                "action": "approve",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)

        # Only real episode should be processed
        data = resp.data["data"]
        self.assertEqual(len(data["processed"]), 1)
        self.assertEqual(len(data["skipped"]), 1)
        self.assertIn(fake_id, data["skipped"])

    def test_bulk_review_response_includes_counts(self):
        """Bulk review response includes processed and skipped counts."""
        ep = make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id)],
                "action": "approve",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("data", resp.data)

        data = resp.data["data"]
        self.assertIn("processed", data)
        self.assertIn("skipped", data)
        self.assertIsInstance(data["processed"], list)
        self.assertIsInstance(data["skipped"], list)

    def test_bulk_review_admin_without_permission_returns_403(self):
        """Admin without CONTENT_MANAGE permission gets 403."""
        ep = make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        admin, role = make_admin_with_role([])
        client = admin_auth_client(admin)
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id)],
                "action": "approve",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 403)

    def test_bulk_review_unauthenticated_returns_403(self):
        """Unauthenticated request returns 403."""
        ep = make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = anon_client()
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id)],
                "action": "approve",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 403)

    def test_bulk_review_sets_reviewer_metadata(self):
        """Bulk review sets reviewed_by and reviewed_at."""
        ep = make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        self.assertIsNone(ep.reviewed_by)
        self.assertIsNone(ep.reviewed_at)

        client = admin_auth_client(self.super_admin)
        before_time = timezone.now()
        resp = client.post(
            f"{BASE}/admin/content/episodes/bulk-review",
            {
                "episode_ids": [str(ep.id)],
                "action": "approve",
            },
            format="json",
        )
        after_time = timezone.now()

        self.assertEqual(resp.status_code, 200)

        ep.refresh_from_db()
        self.assertEqual(ep.reviewed_by, self.super_admin)
        self.assertIsNotNone(ep.reviewed_at)
        self.assertGreaterEqual(ep.reviewed_at, before_time)
        self.assertLessEqual(ep.reviewed_at, after_time)


class ContentApprovalStatsTests(TestCase):
    """Tests for content approval stats endpoint."""

    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)

    def test_content_approval_stats_success(self):
        """Retrieve content approval stats successfully."""
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/stats")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        self.assertIn("data", resp.data)

        # Check stats structure
        stats = resp.data["data"]
        self.assertIn("pending_approval_count", stats)
        self.assertIn("approved_count", stats)
        self.assertIn("rejected_count", stats)
        self.assertIn("avg_review_hour", stats)

    def test_content_approval_stats_with_episodes(self):
        """Stats correctly counts pending and approved episodes."""
        now = timezone.now()
        now.date()

        # Create pending episode
        make_episode(
            self.creator,
            self.season,
            title="Pending",
            order=1,
            status=Episode.Status.REVIEW,
        )

        # Create approved episode (reviewed today)
        approved = make_episode(
            self.creator,
            self.season,
            title="Approved",
            order=2,
            status=Episode.Status.PUBLISHED,
        )
        approved.reviewed_at = now
        approved.reviewed_by = self.super_admin
        approved.save()

        # Create rejected episode (reviewed today)
        rejected = make_episode(
            self.creator,
            self.season,
            title="Rejected",
            order=3,
            status=Episode.Status.REJECTED,
        )
        rejected.reviewed_at = now
        rejected.reviewed_by = self.super_admin
        rejected.save()

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/stats")

        self.assertEqual(resp.status_code, 200)
        stats = resp.data["data"]
        self.assertEqual(stats["pending_approval_count"], 1)
        self.assertEqual(stats["approved_count"], 1)
        self.assertEqual(stats["rejected_count"], 1)

    def test_content_approval_stats_avg_review_hour(self):
        """Stats calculates average review hours correctly."""
        now = timezone.now()

        # Create episode reviewed 2 hours ago
        ep1 = make_episode(
            self.creator,
            self.season,
            title="Episode 1",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        ep1.submitted_for_review_at = now - timedelta(hours=2)
        ep1.reviewed_at = now
        ep1.reviewed_by = self.super_admin
        ep1.save()

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/stats")

        self.assertEqual(resp.status_code, 200)
        stats = resp.data["data"]
        self.assertIsNotNone(stats["avg_review_hour"])
        # Should be approximately 2.0 hours
        self.assertAlmostEqual(float(stats["avg_review_hour"]), 2.0, places=1)

    def test_content_approval_stats_admin_with_permission_success(self):
        """Admin with CONTENT_MANAGE permission can access stats."""
        admin, role = make_admin_with_role([Permission.CONTENT_MANAGE])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/approval/stats")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_content_approval_stats_admin_without_permission_returns_403(self):
        """Admin without CONTENT_MANAGE permission gets 403."""
        admin, role = make_admin_with_role([])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/approval/stats")

        self.assertEqual(resp.status_code, 403)

    def test_content_approval_stats_unauthenticated_returns_403(self):
        """Unauthenticated request returns 403."""
        client = anon_client()
        resp = client.get(f"{BASE}/admin/content/approval/stats")

        self.assertEqual(resp.status_code, 403)


class ContentApprovalListTests(TestCase):
    """Tests for content approval list endpoint."""

    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)

    def test_content_approval_list_success(self):
        """Retrieve content approval list successfully."""
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        self.assertIn("data", resp.data)

        # Check pagination structure
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)

    def test_content_approval_list_includes_episode_fields(self):
        """List includes all required episode fields."""
        make_episode(
            self.creator,
            self.season,
            title="Test Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        if results:
            episode = results[0]
            self.assertIn("episode_id", episode)
            self.assertIn("episode_title", episode)
            self.assertIn("creator_name", episode)
            self.assertIn("skillworld", episode)
            self.assertIn("season_title", episode)
            self.assertIn("status", episode)
            self.assertIn("task_type", episode)
            self.assertIn("submitted_at", episode)
            self.assertIn("video_duration", episode)

    def test_content_approval_list_filter_awaiting_review(self):
        """Filter list by awaiting_review status."""
        # Create episodes in different statuses
        make_episode(
            self.creator,
            self.season,
            title="Under Review",
            order=1,
            status=Episode.Status.REVIEW,
        )
        make_episode(
            self.creator,
            self.season,
            title="Approved",
            order=2,
            status=Episode.Status.PUBLISHED,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list?status=awaiting_review")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        # All results should have REVIEW status
        for episode in results:
            self.assertEqual(episode["status"], Episode.Status.REVIEW)

    def test_content_approval_list_filter_approved(self):
        """Filter list by approved status."""
        # Create episodes in different statuses
        make_episode(
            self.creator,
            self.season,
            title="Under Review",
            order=1,
            status=Episode.Status.REVIEW,
        )
        make_episode(
            self.creator,
            self.season,
            title="Approved",
            order=2,
            status=Episode.Status.PUBLISHED,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list?status=approved")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        # All results should have PUBLISHED status
        for episode in results:
            self.assertEqual(episode["status"], Episode.Status.PUBLISHED)

    def test_content_approval_list_filter_rejected(self):
        """Filter list by rejected status."""
        # Create episodes in different statuses
        make_episode(
            self.creator,
            self.season,
            title="Under Review",
            order=1,
            status=Episode.Status.REVIEW,
        )
        make_episode(
            self.creator,
            self.season,
            title="Rejected",
            order=2,
            status=Episode.Status.REJECTED,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list?status=rejected")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        # All results should have REJECTED status
        for episode in results:
            self.assertEqual(episode["status"], Episode.Status.REJECTED)

    def test_content_approval_list_invalid_status_filter_returns_400(self):
        """Invalid status filter returns 400."""
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list?status=invalid_status")

        self.assertEqual(resp.status_code, 400)

    def test_content_approval_list_no_filter_returns_all(self):
        """No status filter returns all episodes."""
        # Create episodes in different statuses
        make_episode(
            self.creator,
            self.season,
            title="Under Review",
            order=1,
            status=Episode.Status.REVIEW,
        )
        make_episode(
            self.creator,
            self.season,
            title="Approved",
            order=2,
            status=Episode.Status.PUBLISHED,
        )
        make_episode(
            self.creator,
            self.season,
            title="Rejected",
            order=3,
            status=Episode.Status.REJECTED,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        # Should have all three episodes
        self.assertEqual(len(results), 3)

    def test_content_approval_list_pagination(self):
        """List supports pagination."""
        # Create multiple episodes across different seasons (max 10 per season)
        for i in range(15):
            # Create a new season for every 10 episodes
            season = self.season if i < 10 else make_season(self.creator)
            make_episode(
                self.creator,
                season,
                title=f"Episode {i + 1}",
                order=(i % 10) + 1,
                status=Episode.Status.REVIEW,
            )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list?limit=5")

        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]

        # Should be paginated
        self.assertEqual(data["count"], 15)
        self.assertIsNotNone(data.get("next"))

    def test_content_approval_list_admin_with_permission_success(self):
        """Admin with CONTENT_MANAGE permission can access list."""
        make_episode(
            self.creator,
            self.season,
            title="Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        admin, role = make_admin_with_role([Permission.CONTENT_MANAGE])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/approval/list")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_content_approval_list_admin_without_permission_returns_403(self):
        """Admin without CONTENT_MANAGE permission gets 403."""
        admin, role = make_admin_with_role([])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/approval/list")

        self.assertEqual(resp.status_code, 403)

    def test_content_approval_list_unauthenticated_returns_403(self):
        """Unauthenticated request returns 403."""
        client = anon_client()
        resp = client.get(f"{BASE}/admin/content/approval/list")

        self.assertEqual(resp.status_code, 403)

    def test_content_approval_list_includes_creator_name(self):
        """List includes creator name (first + last or email fallback)."""
        make_episode(
            self.creator,
            self.season,
            title="Test Episode",
            order=1,
            status=Episode.Status.REVIEW,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/content/approval/list")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]

        if results:
            episode = results[0]
            self.assertIsNotNone(episode["creator_name"])
            self.assertGreater(len(episode["creator_name"]), 0)
