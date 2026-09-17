import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from skiflux.models import User
from skiflux.models.content import Episode, EpisodeComment
from skiflux.repositories.moderation_repository import ModerationRepository
from skiflux.models.moderation import (
    CommentReport,
    ModerationActionLog,
    UserSuspension,
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


def make_comment(user, episode, text="Test comment", flagged=False):
    comment = EpisodeComment.objects.create(
        user=user,
        episode=episode,
        text=text,
        flagged=flagged,
    )
    if flagged and not comment.flagged_at:
        comment.flagged_at = timezone.now()
        comment.save(update_fields=["flagged_at"])
    return comment


def make_suspension(
    user,
    suspended_by=None,
    reason="Toxic language",
    duration_days=7,
    source=UserSuspension.SuspendedBySource.ADMIN,
):
    repo = ModerationRepository()
    return repo.create_suspension(
        user=user,
        suspended_by=suspended_by,
        reason=reason,
        duration_days=duration_days,
        source=source,
    )


# ─────────────────────────────────────────
# Stats
# ─────────────────────────────────────────


class ModerationStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Stats Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.user = make_verified_user(email="statsuser@example.com")

    def test_stats_returns_expected_shape(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("flagged_today", data)
        self.assertIn("resolved_today", data)
        self.assertIn("active_suspensions", data)
        self.assertIn("total_reports_this_week", data)
        self.assertIn("reports_vs_last_week_pct", data)

    def test_flagged_today_count(self):
        make_comment(self.user, self.episode, flagged=True)
        make_comment(self.user, self.episode, flagged=True)
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/stats/")
        self.assertEqual(resp.data["data"]["flagged_today"], 2)

    def test_active_suspensions_count(self):
        make_suspension(self.user, suspended_by=self.super_admin)
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/stats/")
        self.assertEqual(resp.data["data"]["active_suspensions"], 1)

    def test_total_reports_this_week(self):
        comment = make_comment(self.user, self.episode)
        reporter = make_verified_user(email="reporter@example.com")
        CommentReport.objects.create(
            comment=comment,
            reported_by=reporter,
            category=CommentReport.Category.SPAM,
        )
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/stats/")
        self.assertEqual(resp.data["data"]["total_reports_this_week"], 1)

    def test_admin_with_moderation_view_can_get_stats(self):
        admin, _ = make_admin_with_role(
            [Permission.MODERATION_VIEW],
            email="modstatsviewer@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/moderation/stats/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_without_moderation_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="modstatsblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/moderation/stats/")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_is_blocked(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/moderation/stats/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Flagged Content
# ─────────────────────────────────────────


class FlaggedContentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Flagged Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.user = make_verified_user(email="flaggeduser@example.com")
        self.comment = make_comment(
            self.user,
            self.episode,
            text="This is garbage",
            flagged=True,
        )
        reporter = make_verified_user(email="flaggedreporter@example.com")
        CommentReport.objects.create(
            comment=self.comment,
            reported_by=reporter,
            category=CommentReport.Category.TOXIC_LANGUAGE,
        )

    def test_super_admin_can_list_flagged_comments(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/flagged/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.data["data"]
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["text"], "This is garbage")

    def test_flagged_list_includes_report_count(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/flagged/")
        result = resp.data["data"]["results"][0]
        self.assertEqual(result["report_count"], 1)

    def test_flagged_list_excludes_unflagged_comments(self):
        make_comment(self.user, self.episode, text="Normal comment", flagged=False)
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/flagged/")
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_delete_action_removes_comment(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "delete", "reason": "Spam"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(EpisodeComment.objects.filter(id=self.comment.id).exists())

    def test_delete_action_logs_to_action_log(self):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "delete", "reason": "Spam"},
            format="json",
        )
        self.assertTrue(
            ModerationActionLog.objects.filter(
                action_type=ModerationActionLog.ActionType.COMMENT_DELETED,
                target_user=self.user,
            ).exists()
        )

    def test_delete_action_resolves_pending_reports(self):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "delete"},
            format="json",
        )
        self.assertFalse(
            CommentReport.objects.filter(
                comment=self.comment,
                status=CommentReport.Status.PENDING,
            ).exists()
        )

    @patch("skiflux.services.moderation_service.send_warning_email")
    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_warn_action_sends_email_and_notification(self, mock_notify, mock_email):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {
                "action": "warn",
                "category": "toxic_language",
                "message": "Your comment violated community guidelines.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        mock_email.assert_called_once()
        mock_notify.assert_called_once()

    @patch("skiflux.services.moderation_service.send_warning_email")
    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_warn_action_logs_to_action_log(self, mock_notify, mock_email):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {
                "action": "warn",
                "category": "toxic_language",
                "message": "Please follow community guidelines.",
            },
            format="json",
        )
        self.assertTrue(
            ModerationActionLog.objects.filter(
                action_type=ModerationActionLog.ActionType.WARNING_ISSUED,
                target_user=self.user,
            ).exists()
        )

    def test_warn_action_requires_category_and_message(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "warn"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_suspend_action_creates_suspension(self, mock_notify):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {
                "action": "suspend",
                "reason": "Repeated toxic language",
                "duration_days": 7,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            UserSuspension.objects.filter(
                user=self.user,
                status=UserSuspension.Status.ACTIVE,
            ).exists()
        )

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_suspend_action_updates_user_status(self, mock_notify):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {
                "action": "suspend",
                "reason": "Spam",
                "duration_days": 7,
            },
            format="json",
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, User.Status.SUSPENDED)

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_suspend_action_permanent_when_duration_null(self, mock_notify):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {
                "action": "suspend",
                "reason": "Severe violation",
                "duration_days": None,
            },
            format="json",
        )
        suspension = UserSuspension.objects.get(user=self.user)
        self.assertTrue(suspension.is_permanent)
        self.assertIsNone(suspension.expires_at)

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_suspend_action_requires_duration_days_key(self, mock_notify):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "suspend", "reason": "Spam"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_dismiss_action_unflagged_comment(self):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "dismiss"},
            format="json",
        )
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.flagged)

    def test_dismiss_action_dismisses_pending_reports(self):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "dismiss"},
            format="json",
        )
        self.assertFalse(
            CommentReport.objects.filter(
                comment=self.comment,
                status=CommentReport.Status.PENDING,
            ).exists()
        )

    def test_dismiss_action_logs_to_action_log(self):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "dismiss"},
            format="json",
        )
        self.assertTrue(
            ModerationActionLog.objects.filter(
                action_type=ModerationActionLog.ActionType.REPORT_DISMISSED,
                target_user=self.user,
            ).exists()
        )

    def test_invalid_action_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "ban"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_nonexistent_comment_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{uuid.uuid4()}/action/",
            {"action": "dismiss"},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_admin_without_moderation_manage_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.MODERATION_VIEW],
            email="modviewonly@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(
            f"{BASE}/admin/moderation/flagged/{self.comment.id}/action/",
            {"action": "dismiss"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# All Comments
# ─────────────────────────────────────────


class AllCommentsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Comments Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.user = make_verified_user(
            email="commentsuser@example.com", username="@user-name"
        )
        self.comment = make_comment(self.user, self.episode, text="Great episode!")
        self.flagged_comment = make_comment(
            self.user,
            self.episode,
            text="Toxic comment",
            flagged=True,
        )

    def test_super_admin_can_list_all_comments(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/comments/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 2)

    def test_filter_flagged_returns_only_flagged(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/comments/?filter=flagged")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)
        self.assertEqual(resp.data["data"]["results"][0]["text"], "Toxic comment")

    def test_search_by_username(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/comments/?search={self.user.username}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(resp.data["data"]["count"], 0)

    def test_search_by_comment_text(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/comments/?search=Great")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_invalid_filter_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/comments/?filter=invalid")
        self.assertEqual(resp.status_code, 400)

    def test_delete_comment_removes_it(self):
        client = admin_auth_client(self.super_admin)
        resp = client.delete(f"{BASE}/admin/moderation/comments/{self.comment.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(EpisodeComment.objects.filter(id=self.comment.id).exists())

    def test_delete_nonexistent_comment_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.delete(f"{BASE}/admin/moderation/comments/{uuid.uuid4()}/")
        self.assertEqual(resp.status_code, 404)

    def test_admin_without_moderation_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="commentsblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/moderation/comments/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Suspensions
# ─────────────────────────────────────────


class SuspensionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.user = make_verified_user(email="suspendeduser@example.com")
        self.suspension = make_suspension(
            self.user,
            suspended_by=self.super_admin,
        )

    def test_super_admin_can_list_active_suspensions(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/suspensions/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_suspension_response_includes_expected_fields(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/suspensions/")
        row = resp.data["data"]["results"][0]
        self.assertIn("user", row)
        self.assertIn("suspended_by_label", row)
        self.assertIn("display_duration", row)
        self.assertIn("is_permanent", row)
        self.assertIn("expires_at", row)
        self.assertIn("status", row)

    def test_display_duration_shows_days(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/suspensions/")
        row = resp.data["data"]["results"][0]
        self.assertEqual(row["display_duration"], "7d")

    def test_permanent_suspension_shows_correct_label(self):
        perm_user = make_verified_user(email="permsuspended@example.com")
        make_suspension(perm_user, duration_days=None)
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/suspensions/")
        results = resp.data["data"]["results"]
        perm_row = next(
            r for r in results if r["user"]["email"] == "permsuspended@example.com"
        )
        self.assertEqual(perm_row["display_duration"], "Permanent")
        self.assertTrue(perm_row["is_permanent"])

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_lift_suspension_changes_status(self, mock_notify):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/suspensions/{self.suspension.id}/lift/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.suspension.refresh_from_db()
        self.assertEqual(self.suspension.status, UserSuspension.Status.LIFTED)

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_lift_suspension_restores_user_status(self, mock_notify):
        client = admin_auth_client(self.super_admin)
        self.user.status = User.Status.SUSPENDED
        self.user.save(update_fields=["status"])
        client.post(
            f"{BASE}/admin/moderation/suspensions/{self.suspension.id}/lift/",
            {},
            format="json",
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, User.Status.ACTIVE)

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_lift_suspension_logs_action(self, mock_notify):
        client = admin_auth_client(self.super_admin)
        client.post(
            f"{BASE}/admin/moderation/suspensions/{self.suspension.id}/lift/",
            {},
            format="json",
        )
        self.assertTrue(
            ModerationActionLog.objects.filter(
                action_type=ModerationActionLog.ActionType.SUSPENSION_LIFTED,
                target_user=self.user,
            ).exists()
        )

    @patch(
        "skiflux.services.moderation_service.NotificationService.create_notification"
    )
    def test_lift_already_lifted_suspension_returns_400(self, mock_notify):
        self.suspension.status = UserSuspension.Status.LIFTED
        self.suspension.save(update_fields=["status"])
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/suspensions/{self.suspension.id}/lift/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_lift_nonexistent_suspension_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.post(
            f"{BASE}/admin/moderation/suspensions/{uuid.uuid4()}/lift/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_without_moderation_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="suspensionsblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/moderation/suspensions/")
        self.assertEqual(resp.status_code, 403)

    def test_admin_without_moderation_manage_cannot_lift(self):
        admin, _ = make_admin_with_role(
            [Permission.MODERATION_VIEW],
            email="suspensionsviewonly@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(
            f"{BASE}/admin/moderation/suspensions/{self.suspension.id}/lift/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Action Log
# ─────────────────────────────────────────


class ActionLogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Log Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.user = make_verified_user(email="loguser@example.com")
        self.comment = make_comment(self.user, self.episode)

        ModerationActionLog.objects.create(
            action_type=ModerationActionLog.ActionType.COMMENT_DELETED,
            performed_by=self.super_admin,
            target_user=self.user,
            comment=self.comment,
            reason="Spam link",
        )
        ModerationActionLog.objects.create(
            action_type=ModerationActionLog.ActionType.WARNING_ISSUED,
            performed_by=self.super_admin,
            target_user=self.user,
            reason="Harassment",
        )
        ModerationActionLog.objects.create(
            action_type=ModerationActionLog.ActionType.SUSPENSION,
            performed_by=self.super_admin,
            target_user=self.user,
            reason="Toxic language",
        )

    def test_super_admin_can_get_action_log(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/action-log/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 3)

    def test_action_log_filter_by_deletions(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/action-log/"
            f"?action_type={ModerationActionLog.ActionType.COMMENT_DELETED}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_action_log_filter_by_warnings(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/action-log/"
            f"?action_type={ModerationActionLog.ActionType.WARNING_ISSUED}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_action_log_filter_by_suspensions(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/action-log/"
            f"?action_type={ModerationActionLog.ActionType.SUSPENSION}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)

    def test_invalid_action_type_returns_400(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/action-log/?action_type=invalid")
        self.assertEqual(resp.status_code, 400)

    def test_action_log_export_csv(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/moderation/action-log/export/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn(
            "attachment; filename",
            resp["Content-Disposition"],
        )
        content = resp.content.decode("utf-8")
        self.assertIn("Action", content)
        self.assertIn("Target User", content)
        self.assertIn("Comment Deleted", content)

    def test_admin_without_moderation_view_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="logblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/moderation/action-log/")
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────
# Report Comment (Learner)
# ─────────────────────────────────────────


class ReportCommentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="Report Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.user = make_verified_user(email="reportcommentuser@example.com")
        self.reporter = make_verified_user(email="thereporter@example.com")
        self.comment = make_comment(self.user, self.episode, text="Come to my DMs")

    def _learner_client(self, user):
        from skiflux.utils.auth import create_access_token

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(str(user.id))}"
        )
        return client

    def test_learner_can_report_comment(self):
        client = self._learner_client(self.reporter)
        resp = client.post(
            f"{BASE}/comments/{self.comment.id}/report/",
            {"category": CommentReport.Category.INAPPROPRIATE_SOLICITATION},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            CommentReport.objects.filter(
                comment=self.comment,
                reported_by=self.reporter,
            ).exists()
        )

    def test_cannot_report_same_comment_twice(self):
        client = self._learner_client(self.reporter)
        client.post(
            f"{BASE}/comments/{self.comment.id}/report/",
            {"category": CommentReport.Category.SPAM},
            format="json",
        )
        resp = client.post(
            f"{BASE}/comments/{self.comment.id}/report/",
            {"category": CommentReport.Category.SPAM},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_comment_auto_flagged_report(self):
        reporter = make_verified_user(email="autoflag@example.com")
        client = self._learner_client(reporter)
        client.post(
            f"{BASE}/comments/{self.comment.id}/report/",
            {"category": CommentReport.Category.SPAM},
            format="json",
        )
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.flagged)

    def test_invalid_category_returns_400(self):
        client = self._learner_client(self.reporter)
        resp = client.post(
            f"{BASE}/comments/{self.comment.id}/report/",
            {"category": "not_a_category"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_nonexistent_comment_returns_404(self):
        client = self._learner_client(self.reporter)
        resp = client.post(
            f"{BASE}/comments/{uuid.uuid4()}/report/",
            {"category": CommentReport.Category.SPAM},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)


class SuspensionExpiryTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.user = make_verified_user(email="expiryuser@example.com")

    def test_expired_suspensions_are_marked_expired(self):
        suspension = make_suspension(self.user, suspended_by=self.super_admin)
        UserSuspension.objects.filter(id=suspension.id).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        count = ModerationRepository().expire_due_suspensions()
        self.assertEqual(count, 1)
        suspension.refresh_from_db()
        self.assertEqual(suspension.status, UserSuspension.Status.EXPIRED)

    def test_expiry_restores_user_status(self):
        self.user.status = User.Status.SUSPENDED
        self.user.save(update_fields=["status"])
        suspension = make_suspension(self.user, suspended_by=self.super_admin)
        UserSuspension.objects.filter(id=suspension.id).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        ModerationRepository().expire_due_suspensions()
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, User.Status.ACTIVE)

    def test_permanent_suspension_not_expired(self):
        suspension = make_suspension(
            self.user,
            suspended_by=self.super_admin,
            duration_days=None,
        )
        count = ModerationRepository().expire_due_suspensions()
        self.assertEqual(count, 0)
        suspension.refresh_from_db()
        self.assertEqual(suspension.status, UserSuspension.Status.ACTIVE)


class AIFlaggingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="AI Flag Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        self.user = make_verified_user(email="aiflaguser@example.com")
        self.comment = make_comment(
            self.user,
            self.episode,
            text="This is a toxic comment that violates guidelines",
            flagged=False,
        )
        self.moderation_service = None
        from skiflux.services.moderation_service import ModerationService

        self.moderation_service = ModerationService()

    def test_ai_flag_creates_flag_on_comment(self):
        """Test that AI flagging marks the comment as flagged"""
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Toxic language detected",
            confidence=0.95,
            auto_suspend=False,
        )

        self.comment.refresh_from_db()
        self.assertTrue(self.comment.flagged)

    def test_ai_flag_does_not_create_user_report(self):
        """Test that AI flagging does NOT create a CommentReport"""
        initial_report_count = CommentReport.objects.filter(
            comment=self.comment
        ).count()

        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Toxic language detected",
            confidence=0.95,
            auto_suspend=False,
        )

        final_report_count = CommentReport.objects.filter(comment=self.comment).count()
        self.assertEqual(initial_report_count, final_report_count)
        self.assertEqual(final_report_count, 0)

    def test_ai_flag_logs_action_with_ai_source(self):
        """Test that AI flagging creates a ModerationActionLog with source=AI"""
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Toxic language detected",
            confidence=0.95,
            auto_suspend=False,
        )

        log = ModerationActionLog.objects.filter(
            comment=self.comment,
            source=ModerationActionLog.Source.AI,
        ).first()

        self.assertIsNotNone(log)
        self.assertEqual(log.action_type, ModerationActionLog.ActionType.AI_FLAGGED)
        self.assertIsNone(log.performed_by)
        self.assertEqual(log.reason, "Toxic language detected")
        self.assertEqual(log.metadata.get("confidence"), 0.95)
        self.assertEqual(log.metadata.get("auto_suspend"), False)

    def test_ai_flag_with_auto_suspend_creates_suspension(self):
        """Test that auto_suspend=True creates a suspension for the user"""
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Severe violation",
            confidence=0.98,
            auto_suspend=True,
            duration_days=3,
        )

        suspension = UserSuspension.objects.filter(
            user=self.user,
            source=UserSuspension.SuspendedBySource.AI,
        ).first()

        self.assertIsNotNone(suspension)
        self.assertEqual(suspension.reason, "AI auto-moderation: Severe violation")
        self.assertEqual(suspension.duration_days, 3)
        self.assertEqual(suspension.status, UserSuspension.Status.ACTIVE)
        self.assertIsNone(suspension.suspended_by)  # AI, not admin

    def test_ai_flag_with_auto_suspend_updates_user_status(self):
        """Test that auto_suspend=True updates the user's status to SUSPENDED"""
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Severe violation",
            confidence=0.98,
            auto_suspend=True,
            duration_days=3,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.status, User.Status.SUSPENDED)

    def test_ai_flag_with_auto_suspend_creates_notification(self):
        """Test that auto_suspend=True creates an in-app notification"""
        with patch.object(
            self.moderation_service.notification_service, "create_notification"
        ) as mock_notify:
            self.moderation_service.handle_ai_flag(
                comment=self.comment,
                reason="Severe violation",
                confidence=0.98,
                auto_suspend=True,
                duration_days=3,
            )

            mock_notify.assert_called_once()
            call_args = mock_notify.call_args[1]
            self.assertEqual(call_args["user"], self.user)
            self.assertEqual(call_args["type"], "moderation_suspension")
            self.assertEqual(call_args["title"], "Account Suspended")

    def test_ai_flag_with_auto_suspend_permanent(self):
        """
        Test that auto_suspend with duration_days=None creates permanent suspension
        """
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Permanent ban violation",
            confidence=0.99,
            auto_suspend=True,
            duration_days=None,
        )

        suspension = UserSuspension.objects.get(user=self.user)
        self.assertTrue(suspension.is_permanent)
        self.assertIsNone(suspension.expires_at)

    def test_ai_flag_logs_correct_action_for_auto_suspend(self):
        """Test that auto_suspend=True logs AI_FLAGGED action"""
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Spam content",
            confidence=0.92,
            auto_suspend=True,
            duration_days=1,
        )

        log = ModerationActionLog.objects.filter(
            comment=self.comment,
            source=ModerationActionLog.Source.AI,
        ).first()

        self.assertEqual(log.action_type, ModerationActionLog.ActionType.AI_FLAGGED)

    def test_ai_flag_multiple_times_on_same_comment(self):
        """Test that AI flagging multiple times doesn't duplicate actions"""
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="First flag",
            confidence=0.90,
            auto_suspend=False,
        )

        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Second flag",
            confidence=0.95,
            auto_suspend=False,
        )

        # Should still only have one flag (idempotent)
        logs = ModerationActionLog.objects.filter(
            comment=self.comment,
            source=ModerationActionLog.Source.AI,
        )

        self.assertEqual(logs.count(), 2)  # Two separate AI evaluations logged

        # But comment should still be flagged (no duplicate flagging needed)
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.flagged)

        # No reports created
        reports = CommentReport.objects.filter(comment=self.comment)
        self.assertEqual(reports.count(), 0)

    def test_ai_flag_does_not_affect_existing_user_reports(self):
        """Test that AI flagging doesn't interfere with existing user reports"""
        # Create a user report first
        reporter = make_verified_user(email="reporter@example.com")
        CommentReport.objects.create(
            comment=self.comment,
            reported_by=reporter,
            category=CommentReport.Category.SPAM,
        )

        # Then AI flag
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="AI detected toxicity",
            confidence=0.88,
            auto_suspend=False,
        )

        # User report should still exist
        reports = CommentReport.objects.filter(comment=self.comment)
        self.assertEqual(reports.count(), 1)
        self.assertEqual(reports.first().category, CommentReport.Category.SPAM)
        self.assertEqual(reports.first().status, CommentReport.Status.PENDING)

    def test_ai_flag_metadata_stores_confidence_scores(self):
        """Test that confidence score is properly stored in metadata"""
        confidence = 0.875
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Test reason",
            confidence=confidence,
            auto_suspend=False,
        )

        log = ModerationActionLog.objects.filter(comment=self.comment).first()
        self.assertEqual(log.metadata["confidence"], confidence)

    def test_ai_flag_without_auto_suspend_does_not_change_user_status(self):
        """Test that auto_suspend=False doesn't affect user status"""
        original_status = self.user.status

        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Mild violation",
            confidence=0.75,
            auto_suspend=False,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.status, original_status)
        self.assertEqual(self.user.status, User.Status.ACTIVE)

    def test_ai_flag_on_already_flagged_comment(self):
        """Test AI flagging on a comment that's already flagged"""
        # First, flag the comment via user reports
        self.comment.flagged = True
        self.comment.save()

        # Then AI flag again
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Additional AI detection",
            confidence=0.93,
            auto_suspend=False,
        )

        # Should still log the AI action
        log = ModerationActionLog.objects.filter(
            comment=self.comment,
            source=ModerationActionLog.Source.AI,
        ).first()

        self.assertIsNotNone(log)
        self.assertEqual(log.reason, "Additional AI detection")

        # Comment remains flagged
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.flagged)

    def test_ai_flag_with_auto_suspend_logs_suspension_metadata(self):
        """Test that suspension metadata is properly logged"""
        self.moderation_service.handle_ai_flag(
            comment=self.comment,
            reason="Auto-suspend test",
            confidence=0.96,
            auto_suspend=True,
            duration_days=5,
        )

        log = ModerationActionLog.objects.filter(
            comment=self.comment,
            source=ModerationActionLog.Source.AI,
        ).first()

        self.assertIn("auto_suspend", log.metadata)
        self.assertTrue(log.metadata["auto_suspend"])
        self.assertEqual(log.metadata["confidence"], 0.96)


class UserFlaggedCommentsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            title="User Flagged Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
        )

        self.user = make_verified_user(email="userflagged@example.com")
        self.other_user = make_verified_user(email="otheruser@example.com")

        self.flagged_comment = make_comment(
            self.user,
            self.episode,
            text="This is toxic",
            flagged=True,
        )
        self.unflagged_comment = make_comment(
            self.user,
            self.episode,
            text="A normal comment",
            flagged=False,
        )
        self.other_user_flagged_comment = make_comment(
            self.other_user,
            self.episode,
            text="Someone else's toxic comment",
            flagged=True,
        )

        self.reporter = make_verified_user(email="userflaggedreporter@example.com")
        CommentReport.objects.create(
            comment=self.flagged_comment,
            reported_by=self.reporter,
            category=CommentReport.Category.TOXIC_LANGUAGE,
        )

        second_reporter = make_verified_user(email="userflaggedreporter2@example.com")
        CommentReport.objects.create(
            comment=self.flagged_comment,
            reported_by=second_reporter,
            category=CommentReport.Category.HARASSMENT,
        )

    def test_list_nonexistent_user_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{uuid.uuid4()}/flagged-comments/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_admin_without_moderation_view_is_blocked_on_list(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="userflaggedlistblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_is_blocked_on_list(self):
        client = APIClient()
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        self.assertEqual(resp.status_code, 403)

    # ── Detail endpoint ─────────────────────

    def test_super_admin_can_get_single_flagged_comment_for_user(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}"
            f"/flagged-comments/{self.flagged_comment.id}/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["text"], "This is toxic")
        self.assertEqual(resp.data["data"]["report_count"], 2)

    def test_detail_for_unflagged_comment_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}"
            f"/flagged-comments/{self.unflagged_comment.id}/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_for_comment_belonging_to_other_user_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}"
            f"/flagged-comments/{self.other_user_flagged_comment.id}/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_nonexistent_comment_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}"
            f"/flagged-comments/{uuid.uuid4()}/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_nonexistent_user_returns_404(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{uuid.uuid4()}"
            f"/flagged-comments/{self.flagged_comment.id}/"
        )
        self.assertEqual(resp.status_code, 404)

    def test_admin_without_moderation_view_is_blocked_on_detail(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="userflaggeddetailblocked@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}"
            f"/flagged-comments/{self.flagged_comment.id}/"
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_is_blocked_on_detail(self):
        client = APIClient()
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}"
            f"/flagged-comments/{self.flagged_comment.id}/"
        )
        self.assertEqual(resp.status_code, 403)

    # ── List endpoint ──────────────────────

    def test_super_admin_can_list_user_flagged_comments(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "This is toxic")

    def test_list_excludes_unflagged_comments(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        texts = [c["text"] for c in resp.data["data"]]
        self.assertNotIn("A normal comment", texts)

    def test_list_excludes_other_users_comments(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        texts = [c["text"] for c in resp.data["data"]]
        self.assertNotIn("Someone else's toxic comment", texts)

    def test_list_includes_report_count(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        result = resp.data["data"][0]
        self.assertEqual(result["report_count"], 2)
        self.assertEqual(result["pending_report_count"], 2)

    def test_list_includes_report_category_breakdown(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        result = resp.data["data"][0]
        categories = {
            entry["category"]: entry["count"]
            for entry in result["report_category_breakdown"]
        }
        self.assertEqual(categories[CommentReport.Category.TOXIC_LANGUAGE], 1)
        self.assertEqual(categories[CommentReport.Category.HARASSMENT], 1)

    def test_list_includes_reported_user_details(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        result = resp.data["data"][0]
        self.assertEqual(result["user"]["id"], str(self.user.id))
        self.assertEqual(result["user"]["email"], self.user.email)

    def test_list_includes_episode_and_season_details(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{self.user.id}/flagged-comments/"
        )
        result = resp.data["data"][0]
        self.assertEqual(result["episode"]["id"], str(self.episode.id))
        self.assertEqual(result["episode"]["season"]["id"], str(self.season.id))

    def test_list_for_user_with_no_flagged_comments_returns_empty(self):
        empty_user = make_verified_user(email="noflags@example.com")
        client = admin_auth_client(self.super_admin)
        resp = client.get(
            f"{BASE}/admin/moderation/users/{empty_user.id}/flagged-comments/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"], [])
