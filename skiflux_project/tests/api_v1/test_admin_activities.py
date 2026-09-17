from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from skiflux.models.activity import ActivityLog
from skiflux.models.content import Episode, EpisodeTask, TaskSubmission
from skiflux.models.role import Permission
from skiflux.models.wallet import SkillcoinTransaction, SystemFinancialConfig
from skiflux.services.activity import ActivityService
from skiflux.services.content_service import ContentService
from skiflux.services.wallet_service import WalletService
import uuid

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


class AdminActivityEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

    def test_recent_activities_returns_serialized_logs_without_relative_time(self):
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.ADMIN_CREATED,
            description="Test admin account was created.",
            actor=self.super_admin,
            subject=self.super_admin,
            metadata={"source": "test"},
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/activities/recent?limit=1")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        activity = resp.data["data"][0]
        self.assertEqual(activity["description"], "Test admin account was created.")
        self.assertIn("timestamp", activity)
        self.assertNotIn("timestamp_readable", activity)
        self.assertEqual(activity["actor"]["type"], "admin")

    def test_list_activities_supports_pagination(self):
        for index in range(3):
            ActivityService.log_activity(
                action_type=ActivityLog.ActionType.SYSTEM_ERROR,
                description=f"System event {index}",
            )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/activities?limit=2")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 3)
        self.assertEqual(len(resp.data["data"]["results"]), 2)

    def test_admin_with_analytics_view_can_read_activities(self):
        admin, _ = make_admin_with_role([Permission.ANALYTICS_VIEW])
        client = admin_auth_client(admin)

        resp = client.get(f"{BASE}/admin/activities/recent")

        self.assertEqual(resp.status_code, 200)

    def test_admin_without_analytics_view_is_blocked(self):
        admin, _ = make_admin_with_role([Permission.CONTENT_VIEW])
        client = admin_auth_client(admin)

        resp = client.get(f"{BASE}/admin/activities/recent")

        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_request_is_blocked(self):
        resp = APIClient().get(f"{BASE}/admin/activities/recent")

        self.assertEqual(resp.status_code, 403)


class ActivityIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_episode_review_creates_activity_log(self):
        creator = make_creator()
        season = make_season(creator)
        episode = make_episode(
            creator,
            season,
            status=Episode.Status.REVIEW,
        )
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_MANAGE],
            email="reviewactivity@skiflux.com",
        )

        ContentService().review_episode(
            admin=admin,
            episode_id=str(episode.id),
            action="approve",
        )

        activity = ActivityLog.objects.get(
            action_type=ActivityLog.ActionType.VERIFICATION_APPROVED
        )
        self.assertEqual(activity.actor_admin, admin)
        self.assertEqual(activity.subject_admin, creator)
        self.assertEqual(activity.metadata["episode_id"], str(episode.id))

    def test_submission_approval_creates_activity_log(self):
        config = SystemFinancialConfig.get_config()
        config.max_cashback_amount = Decimal("50.00")
        config.episode_purchase_price_skillcoins = Decimal("10.00")
        config.save()

        user = make_verified_user(email="activitybuyer@example.com")
        creator = make_creator(email="activitycreator@example.com")
        season = make_season(creator)
        episode = make_episode(
            creator,
            season,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.PUBLISHED,
        )
        task = EpisodeTask.objects.create(
            episode=episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            completion_criteria={},
        )
        wallet_service = WalletService()
        wallet_service.credit_wallet(
            user,
            Decimal("10.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Funds",
        )
        wallet_service.credit_platform_wallet(
            Decimal("20.00"),
            SkillcoinTransaction.Type.PLATFORM_REVENUE,
            "Platform funds",
        )
        ContentService().purchase_episode(user, str(episode.id))
        submission = TaskSubmission.objects.create(
            task=task,
            user=user,
            submission_text="Done",
        )
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_MANAGE],
            email="submissionactivity@skiflux.com",
        )

        ContentService().approve_submission(
            admin=admin,
            submission_id=str(submission.id),
            cashback_amount=Decimal("5.00"),
        )

        activity = ActivityLog.objects.get(
            action_type=ActivityLog.ActionType.CONTENT_APPROVED
        )
        self.assertEqual(activity.actor_admin, admin)
        self.assertEqual(activity.subject_user, user)
        self.assertEqual(activity.metadata["submission_id"], str(submission.id))


class UserActivitiesEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.user = make_verified_user(email="useractivities@example.com")
        self.other_user = make_verified_user(email="otheractivities@example.com")

    def test_super_admin_can_list_user_activities(self):
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_WARNING_ISSUED,
            description="Warning issued to user.",
            actor=self.super_admin,
            subject=self.user,
            metadata={"category": "spam"},
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/users/{self.user.id}/activities/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        results = resp.data["data"]["results"]
        self.assertEqual(resp.data["data"]["count"], 1)
        self.assertEqual(results[0]["description"], "Warning issued to user.")
        self.assertEqual(results[0]["actor"]["type"], "admin")
        self.assertEqual(results[0]["subject"]["id"], str(self.user.id))

    def test_includes_activities_where_user_is_actor(self):
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.TRANSACTION_COMPLETED,
            description="User made a deposit.",
            actor=self.user,
            subject=None,
            metadata={"amount": "5000.00"},
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/users/{self.user.id}/activities/")

        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertEqual(resp.data["data"]["count"], 1)
        self.assertEqual(results[0]["description"], "User made a deposit.")
        self.assertEqual(results[0]["actor"]["type"], "user")

    def test_excludes_other_users_activities(self):
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_WARNING_ISSUED,
            description="Warning issued to other user.",
            actor=self.super_admin,
            subject=self.other_user,
        )
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_WARNING_ISSUED,
            description="Warning issued to user.",
            actor=self.super_admin,
            subject=self.user,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/users/{self.user.id}/activities/")

        self.assertEqual(resp.data["data"]["count"], 1)
        descriptions = [r["description"] for r in resp.data["data"]["results"]]
        self.assertIn("Warning issued to user.", descriptions)
        self.assertNotIn("Warning issued to other user.", descriptions)

    def test_default_page_size_is_10(self):
        for index in range(15):
            ActivityService.log_activity(
                action_type=ActivityLog.ActionType.MODERATION_WARNING_ISSUED,
                description=f"Warning {index}",
                actor=self.super_admin,
                subject=self.user,
            )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/users/{self.user.id}/activities/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 15)
        self.assertEqual(len(resp.data["data"]["results"]), 10)
        self.assertIsNotNone(resp.data["data"]["next"])

    def test_ordered_most_recent_first(self):
        first_log = ActivityService.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_WARNING_ISSUED,
            description="First warning",
            actor=self.super_admin,
            subject=self.user,
        )
        # Backdate the first log deterministically — no sleep needed.
        # QuerySet.update() bypasses auto_now_add, allowing direct timestamp write.
        ActivityLog.objects.filter(pk=first_log.pk).update(
            timestamp=timezone.now() - timezone.timedelta(seconds=1)
        )
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.MODERATION_SUSPENSION,
            description="Second warning",
            actor=self.super_admin,
            subject=self.user,
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/users/{self.user.id}/activities/")

        results = resp.data["data"]["results"]
        self.assertEqual(results[0]["description"], "Second warning")
        self.assertEqual(results[1]["description"], "First warning")

    def test_admin_with_analytics_view_can_read(self):
        admin, _ = make_admin_with_role(
            [Permission.USERS_VIEW],
            email="useractivitiesviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/users/{self.user.id}/activities/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_analytics_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="useractivitiesblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/users/{self.user.id}/activities/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_request_is_blocked(self):
        resp = APIClient().get(f"{BASE}/admin/users/{self.user.id}/activities/")
        self.assertEqual(resp.status_code, 403)

    def test_nonexistent_user_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/users/{uuid.uuid4()}/activities/")
        self.assertEqual(resp.status_code, 404)
