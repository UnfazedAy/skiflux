"""
Studio Task Endpoints Tests

Covers:
  1. Get episode task (with submission counts)
  2. Get task submissions (paginated, with SLA)
  3. Get episode comments (paginated)

All endpoints require creator/owner OR admin with CONTENT_VIEW permission.
"""

from django.core.cache import cache
from django.test import TestCase

from skiflux.models import AdminUser
from skiflux.models.content import (
    Episode,
    EpisodeTask,
    TaskSubmission,
    EpisodeComment,
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


class GetEpisodeTaskTests(TestCase):
    """Tests for GET /studio/{episode_id}/tasks/{task_id}/"""

    def setUp(self):
        cache.clear()
        self.creator = make_creator(email="creator@test.com", username="creator1")
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            status=Episode.Status.PUBLISHED,
        )

        # Create a project-based task
        self.project_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Build a website",
            accepted_proof_types=["link", "image"],
        )

        # Create an assessment task
        self.assessment_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.ASSESSMENT,
            pass_score_percent=70,
            time_limit_minutes=30,
        )

        # Create some submissions
        user1 = make_verified_user(email="user1@test.com")
        user2 = make_verified_user(email="user2@test.com")

        TaskSubmission.objects.create(
            task=self.project_task,
            user=user1,
            submission_url="https://example.com",
            status=TaskSubmission.Status.PENDING,
        )
        TaskSubmission.objects.create(
            task=self.project_task,
            user=user2,
            submission_url="https://example.com/2",
            status=TaskSubmission.Status.APPROVED,
        )

    def test_get_task_by_owner_success(self):
        """Creator can retrieve their own episode's task."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/{self.project_task.id}/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["id"], str(self.project_task.id))
        self.assertEqual(data["data"]["kind"], EpisodeTask.Kind.PROJECT_BASED)
        self.assertEqual(data["data"]["total_submissions"], 2)
        self.assertEqual(data["data"]["pending_submissions"], 1)

    def test_get_assessment_task_by_owner(self):
        """Creator can retrieve assessment task with proper submission counts."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/{self.assessment_task.id}/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["kind"], EpisodeTask.Kind.ASSESSMENT)
        self.assertEqual(data["data"]["total_submissions"], 0)
        self.assertEqual(data["data"]["pending_submissions"], 0)

    def test_get_task_by_admin_with_permission(self):
        """Admin with CONTENT_VIEW permission can access."""
        admin, _ = make_admin_with_role(
            permissions=[Permission.CONTENT_VIEW],
            email="admin@test.com",
        )
        client = admin_auth_client(admin)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/{self.project_task.id}/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_get_task_by_non_owner_admin_forbidden(self):
        """Admin without CONTENT_VIEW permission is denied."""
        other_admin = AdminUser.objects.create_admin(
            email="other@test.com",
            first_name="Other",
            password="Pass123!",
        )
        client = admin_auth_client(other_admin)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/{self.project_task.id}/",
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_get_task_nonexistent_returns_400(self):
        """Requesting non-existent task returns 400."""
        import uuid

        fake_task_id = uuid.uuid4()
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/{fake_task_id}/",
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_get_task_wrong_episode_returns_400(self):
        """Task from different episode returns 400."""
        other_creator = make_creator(
            email="other_creator@test.com",
            username="creator2",
        )
        other_season = make_season(other_creator)
        other_episode = make_episode(other_creator, other_season)
        other_task = EpisodeTask.objects.create(
            episode=other_episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Other task",
        )

        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/{other_task.id}/",
            format="json",
        )
        self.assertEqual(response.status_code, 400)


class GetTaskSubmissionsTests(TestCase):
    """Tests for GET /creator/episode/{episode_id}/tasks/{task_id}/submissions/"""

    def setUp(self):
        cache.clear()
        self.creator = make_creator(email="creator@test.com", username="creator1")
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            status=Episode.Status.PUBLISHED,
        )

        # Create a project-based task
        self.project_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Build a website",
        )

        # Create assessment task (should fail when accessing submissions)
        self.assessment_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.ASSESSMENT,
            pass_score_percent=70,
        )

        # Create submissions
        self.user1 = make_verified_user(email="user1@test.com")
        self.user2 = make_verified_user(email="user2@test.com")
        self.user3 = make_verified_user(email="user3@test.com")

        self.pending_sub = TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user1,
            submission_url="https://example.com/1",
            status=TaskSubmission.Status.PENDING,
        )
        self.approved_sub = TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user2,
            submission_url="https://example.com/2",
            status=TaskSubmission.Status.APPROVED,
            cashback_amount=100.00,
        )
        self.rejected_sub = TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user3,
            submission_url="https://example.com/3",
            status=TaskSubmission.Status.REJECTED,
        )

    def test_get_submissions_by_owner_success(self):
        """Creator can retrieve submissions for their task."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["count"], 3)
        self.assertEqual(len(data["data"]["results"]), 3)

    def test_get_submissions_pagination(self):
        """Submissions are paginated correctly."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/?page=1&limit=2",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["count"], 3)
        self.assertEqual(len(data["data"]["results"]), 2)
        self.assertIsNotNone(data["data"]["next"])

    def test_get_submissions_filter_by_status(self):
        """Filter submissions by status."""
        client = admin_auth_client(self.creator)

        # Get pending
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/?status=pending",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["count"], 1)
        self.assertEqual(data["data"]["results"][0]["status"], "pending")

        # Get approved
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/?status=approved",
            format="json",
        )
        data = response.json()
        self.assertEqual(data["data"]["count"], 1)
        self.assertEqual(data["data"]["results"][0]["status"], "approved")

    def test_submissions_have_sla_status(self):
        """Submissions include SLA status (pending, breached, done)."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/",
            format="json",
        )
        data = response.json()
        results = data["data"]["results"]

        # Find pending and approved submissions
        pending = next(r for r in results if r["status"] == "pending")
        approved = next(r for r in results if r["status"] == "approved")

        self.assertIsNotNone(pending["sla"])  # Should have time remaining
        self.assertEqual(approved["sla"], "done")

    def test_assessment_task_submissions_returns_error(self):
        """Accessing submissions on assessment task returns error."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.assessment_task.id}/submissions/",
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_get_submissions_invalid_status_returns_400(self):
        """Invalid status filter returns 400."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/?status=invalid",
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_get_submissions_by_admin_with_permission(self):
        """Admin with CONTENT_VIEW permission can access."""
        admin, _ = make_admin_with_role(
            permissions=[Permission.CONTENT_VIEW],
            email="admin@test.com",
        )
        client = admin_auth_client(admin)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_submissions_list_has_user_info(self):
        """Submissions include user information."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/",
            format="json",
        )
        data = response.json()
        results = data["data"]["results"]

        self.assertTrue(
            any(result["user_email"] == self.user1.email for result in results)
        )
        self.assertTrue(
            any("user_name" in result and "created_at" in result for result in results)
        )


class GetPendingTaskSubmissionsForCreatorTests(TestCase):
    """Tests for GET /admin/studio/creators/{creator_id}/pending-task-submissions/"""

    def setUp(self):
        cache.clear()
        self.creator = make_creator(email="creator@test.com", username="creator1")
        self.other_creator = make_creator(
            email="other_creator@test.com",
            username="creator2",
        )
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            status=Episode.Status.PUBLISHED,
        )
        other_season = make_season(self.other_creator)
        self.other_episode = make_episode(
            self.other_creator,
            other_season,
            status=Episode.Status.PUBLISHED,
        )

        self.project_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Build a website",
        )
        self.assessment_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.ASSESSMENT,
            pass_score_percent=70,
        )
        other_task = EpisodeTask.objects.create(
            episode=self.other_episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Other creator task",
        )

        self.user1 = make_verified_user(email="user1@test.com")
        self.user2 = make_verified_user(email="user2@test.com")
        self.user3 = make_verified_user(email="user3@test.com")

        self.pending_sub = TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user1,
            submission_url="https://example.com/1",
            status=TaskSubmission.Status.PENDING,
        )
        TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user2,
            submission_url="https://example.com/2",
            status=TaskSubmission.Status.APPROVED,
        )
        TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user3,
            submission_url="https://example.com/3",
            status=TaskSubmission.Status.REJECTED,
        )
        TaskSubmission.objects.create(
            task=self.assessment_task,
            user=self.user1,
            submission_text="assessment answer",
            status=TaskSubmission.Status.PENDING,
        )
        TaskSubmission.objects.create(
            task=other_task,
            user=self.user1,
            submission_url="https://example.com/other",
            status=TaskSubmission.Status.PENDING,
        )

    def _url(self, creator_id):
        return f"{BASE}/admin/studio/creators/{creator_id}/pending-task-submissions/"

    def test_creator_can_get_own_pending_submissions(self):
        client = admin_auth_client(self.creator)
        response = client.get(self._url(self.creator.id), format="json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Pending task submissions retrieved.")
        self.assertEqual(data["data"]["count"], 1)
        self.assertEqual(len(data["data"]["results"]), 1)
        result = data["data"]["results"][0]
        self.assertEqual(result["id"], str(self.pending_sub.id))
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["proof_type"], "link")
        self.assertEqual(result["user_email"], self.user1.email)

    def test_pending_submissions_include_sla_for_pending_status(self):
        client = admin_auth_client(self.creator)
        response = client.get(self._url(self.creator.id), format="json")

        result = response.json()["data"]["results"][0]
        self.assertIsNotNone(result["sla"])

    def test_other_creator_forbidden(self):
        client = admin_auth_client(self.other_creator)
        response = client.get(self._url(self.creator.id), format="json")

        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_access_creator_pending_submissions(self):
        super_admin = make_super_admin()
        client = admin_auth_client(super_admin)
        response = client.get(self._url(self.creator.id), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 1)

    def test_admin_with_content_manage_can_access(self):
        admin, _ = make_admin_with_role(
            permissions=[Permission.CONTENT_MANAGE],
            email="contentmanage@test.com",
        )
        client = admin_auth_client(admin)
        response = client.get(self._url(self.creator.id), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 1)

    def test_admin_without_content_manage_forbidden(self):
        admin, _ = make_admin_with_role(
            permissions=[Permission.CONTENT_VIEW],
            email="contentview@test.com",
        )
        client = admin_auth_client(admin)
        response = client.get(self._url(self.creator.id), format="json")

        self.assertEqual(response.status_code, 403)

    def test_unknown_creator_returns_400(self):
        import uuid

        super_admin = make_super_admin()
        client = admin_auth_client(super_admin)
        response = client.get(self._url(uuid.uuid4()), format="json")

        self.assertEqual(response.status_code, 400)


class GetEpisodeCommentsTests(TestCase):
    """Tests for GET /studio/{episode_id}/comments/"""

    def setUp(self):
        cache.clear()
        self.creator = make_creator(email="creator@test.com", username="creator1")
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            status=Episode.Status.PUBLISHED,
        )

        # Create comments
        self.user1 = make_verified_user(email="user1@test.com")
        self.user2 = make_verified_user(email="user2@test.com")
        self.user3 = make_verified_user(email="user3@test.com")

        self.comment1 = EpisodeComment.objects.create(
            episode=self.episode,
            user=self.user1,
            text="Great episode!",
        )
        self.comment2 = EpisodeComment.objects.create(
            episode=self.episode,
            user=self.user2,
            text="Could be better.",
        )
        self.comment3 = EpisodeComment.objects.create(
            episode=self.episode,
            user=self.user3,
            text="Amazing content!",
        )

    def test_get_comments_by_owner_success(self):
        """Creator can retrieve episode comments."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/comments/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["total_count"], 3)
        self.assertEqual(len(data["data"]["results"]), 3)

    def test_get_comments_pagination_default(self):
        """Comments use default pagination (20 per page)."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/comments/",
            format="json",
        )
        data = response.json()
        self.assertEqual(data["data"]["limit"], 20)
        self.assertEqual(data["data"]["offset"], 0)

    def test_get_comments_with_offset_and_limit(self):
        """Comments pagination with custom offset and limit."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/comments/?offset=1&limit=2",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["total_count"], 3)
        self.assertEqual(data["data"]["offset"], 1)
        self.assertEqual(data["data"]["limit"], 2)
        self.assertEqual(len(data["data"]["results"]), 2)

    def test_comments_have_user_info(self):
        """Comments include user information."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/comments/",
            format="json",
        )
        data = response.json()
        result = data["data"]["results"][0]

        self.assertIn("id", result)
        self.assertIn("user_id", result)
        self.assertIn("user_email", result)
        self.assertIn("user_name", result)
        self.assertIn("text", result)
        self.assertIn("created_at", result)

    def test_get_comments_by_admin_with_permission(self):
        """Admin with CONTENT_VIEW permission can access."""
        admin, _ = make_admin_with_role(
            permissions=[Permission.CONTENT_VIEW],
            email="admin@test.com",
        )
        client = admin_auth_client(admin)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/comments/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_get_comments_non_owner_forbidden(self):
        """Non-owner without permission is denied."""
        other_creator = make_creator(email="other@test.com", username="other")
        client = admin_auth_client(other_creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/comments/",
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_get_comments_ordered_by_created_at_desc(self):
        """Comments are ordered by most recent first."""
        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/comments/",
            format="json",
        )
        data = response.json()
        results = data["data"]["results"]

        # Verify descending order (most recent first)
        timestamps = [r["created_at"] for r in results]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_get_comments_empty_episode(self):
        """Episode with no comments returns empty list."""
        other_creator = make_creator(email="other2@test.com", username="other2")
        other_season = make_season(other_creator)
        other_episode = make_episode(other_creator, other_season)

        client = admin_auth_client(other_creator)
        response = client.get(
            f"{BASE}/creator/episode/{other_episode.id}/comments/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["total_count"], 0)
        self.assertEqual(len(data["data"]["results"]), 0)
