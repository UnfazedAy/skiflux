from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from skiflux.models import ActivityLog
from skiflux.models.content import Episode, EpisodeComment, EpisodeTask, TaskSubmission
from skiflux.models.role import Permission
from skiflux.models.wallet import SkillcoinTransaction, UserWallet
from skiflux.services.wallet_service import WalletService

from .conftest import (
    admin_auth_client,
    make_admin_with_role,
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
)

BASE = "/api/v1"


class AdminContentReviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = make_creator(email="review_creator@test.com")
        self.season = make_season(self.creator)
        self.season.price = Decimal("5.00")
        self.season.save()
        self.episode = make_episode(
            self.creator,
            self.season,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.REVIEW,
        )
        self.task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Share a portfolio link",
            accepted_proof_types=["link"],
        )
        self.user = make_verified_user(email="review_user@test.com")
        self.submission = TaskSubmission.objects.create(
            task=self.task,
            user=self.user,
            submission_url="https://example.com/work",
        )
        self.comment = EpisodeComment.objects.create(
            episode=self.episode,
            user=self.user,
            text="Please review this.",
        )
        self.admin, _ = make_admin_with_role(
            [Permission.CONTENT_MANAGE],
            email="content_reviewer@test.com",
        )
        self.client = admin_auth_client(self.admin)

    def test_get_submission_by_id_includes_review_relations(self):
        resp = self.client.get(
            f"{BASE}/admin/content/submissions/{self.submission.id}",
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["id"], str(self.submission.id))
        self.assertEqual(data["task_id"], str(self.task.id))
        self.assertEqual(data["episode_id"], str(self.episode.id))
        self.assertEqual(data["season_id"], str(self.season.id))
        self.assertEqual(data["user_email"], self.user.email)

    def test_reject_submission_stores_reason_feedback_and_logs_activity(self):
        resp = self.client.post(
            f"{BASE}/admin/content/submissions/{self.submission.id}/reject",
            {
                "rejection_reason": "Proof link is not accessible.",
                "feedback": "Please switch sharing to public.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, TaskSubmission.Status.REJECTED)
        self.assertEqual(
            self.submission.rejection_reason, "Proof link is not accessible."
        )
        self.assertEqual(self.submission.feedback, "Please switch sharing to public.")
        self.assertEqual(self.submission.reviewed_by, self.admin)
        self.assertTrue(
            ActivityLog.objects.filter(
                action_type=ActivityLog.ActionType.CONTENT_REJECTED,
                metadata__submission_id=str(self.submission.id),
            ).exists()
        )

    def test_approve_submission_accepts_optional_feedback(self):
        WalletService().credit_platform_wallet(
            Decimal("20.00"),
            SkillcoinTransaction.Type.PLATFORM_REVENUE,
            "Test platform funds",
        )
        resp = self.client.post(
            f"{BASE}/admin/content/submissions/{self.submission.id}/approve",
            {
                "cashback_amount": "3.50",
                "feedback": "Nice work, approved.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, TaskSubmission.Status.APPROVED)
        self.assertEqual(self.submission.feedback, "Nice work, approved.")
        self.assertEqual(self.submission.reviewed_by, self.admin)
        self.assertEqual(
            UserWallet.objects.get(user=self.user).balance, Decimal("3.50")
        )

    def test_get_episode_review_detail_includes_tasks_submissions_comments(self):
        resp = self.client.get(
            f"{BASE}/admin/content/episodes/{self.episode.id}",
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["episode"]["id"], str(self.episode.id))
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(len(data["task_submissions"]), 1)
        self.assertEqual(len(data["comments"]), 1)

    def test_get_tasks_in_season(self):
        resp = self.client.get(
            f"{BASE}/admin/content/seasons/{self.season.id}/tasks",
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["total_count"], 1)
        self.assertEqual(data["results"][0]["id"], str(self.task.id))
        self.assertEqual(data["results"][0]["pending_submissions"], 1)

    def test_get_comments_in_season(self):
        resp = self.client.get(
            f"{BASE}/admin/content/seasons/{self.season.id}/comments",
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["total_count"], 1)
        self.assertEqual(data["results"][0]["id"], str(self.comment.id))
        self.assertEqual(data["results"][0]["episode_id"], str(self.episode.id))
