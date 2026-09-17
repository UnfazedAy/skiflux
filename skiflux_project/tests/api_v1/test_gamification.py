from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from skiflux.models.gamification import Badge, PlatformTask, UserBadge, UserPlatformTask
from skiflux.models.platform_settings import SystemGamificationConfig

from .conftest import (
    admin_auth_client,
    make_super_admin,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class GamificationAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="learner@example.com")
        self.client = user_auth_client(self.user)
        self.superadmin = make_super_admin(email="super@skiflux.com")
        self.admin_client = admin_auth_client(self.superadmin)

        self.task1 = PlatformTask.objects.create(
            slug="complete-profile",
            title="Complete Profile",
            description="Complete your profile info",
            category=PlatformTask.Category.ONBOARDING,
            trigger_type=PlatformTask.TriggerType.COMPLETE_PROFILE,
            verification_mode=PlatformTask.VerificationMode.AUTOMATIC,
            xp_reward=100,
            skillcoin_reward=Decimal("5.00"),
            is_active=True,
        )
        self.task2 = PlatformTask.objects.create(
            slug="refer-a-friend",
            title="Refer a Friend",
            description="Invite a friend to Skiflux",
            category=PlatformTask.Category.REFERRAL,
            trigger_type=PlatformTask.TriggerType.REFER_FRIEND,
            verification_mode=PlatformTask.VerificationMode.AUTOMATIC,
            xp_reward=150,
            skillcoin_reward=Decimal("0.00"),
            is_active=True,
        )
        self.manual_task = PlatformTask.objects.create(
            slug="follow-instagram",
            title="Follow Instagram",
            description="Follow us on Instagram",
            category=PlatformTask.Category.SOCIAL,
            trigger_type="",
            verification_mode=PlatformTask.VerificationMode.MANUAL,
            external_url="https://instagram.com/skiflux",
            xp_reward=25,
            skillcoin_reward=Decimal("25.00"),
            is_active=True,
        )

        self.badge_streak_7 = Badge.objects.create(
            name="7-Day Streak",
            description="Earned for 7 days active streak",
            is_active=True,
        )
        self.badge_rank_amateur = Badge.objects.create(
            name="Amateur Rank",
            description="Achieved Amateur rank",
            is_active=True,
        )

    def test_list_platform_tasks(self):
        resp = self.client.get(f"{BASE}/profile/me/platform-tasks")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(len(data), 3)

        t1 = next(t for t in data if t["id"] == str(self.task1.id))
        self.assertEqual(t1["title"], "Complete Profile")
        self.assertEqual(t1["status"], "not_started")
        self.assertFalse(t1["completed"])
        self.assertIsNone(t1["completed_at"])

        UserPlatformTask.objects.create(
            user=self.user,
            platform_task=self.task1,
            status=UserPlatformTask.Status.CLAIMED,
            progress_current=1,
            claimed_at=timezone.now(),
        )

        resp = self.client.get(f"{BASE}/profile/me/platform-tasks")
        self.assertEqual(resp.status_code, 200)
        t1 = next(t for t in resp.data["data"] if t["id"] == str(self.task1.id))
        self.assertTrue(t1["completed"])
        self.assertIsNotNone(t1["completed_at"])

    def test_manual_task_submit_and_claim_flow(self):
        submit_resp = self.client.post(
            f"{BASE}/profile/me/platform-tasks/{self.manual_task.id}/submit"
        )
        self.assertEqual(submit_resp.status_code, 200)
        self.assertTrue(submit_resp.data["data"]["claimable"])

        claim_resp = self.client.post(
            f"{BASE}/profile/me/platform-tasks/{self.manual_task.id}/claim"
        )
        self.assertEqual(claim_resp.status_code, 200)
        self.assertTrue(claim_resp.data["data"]["completed"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.xp, 25)
        self.assertEqual(self.user.streak_count, 1)

    def test_complete_manual_task_backward_compatible(self):
        resp = self.client.post(
            f"{BASE}/profile/me/platform-tasks/{self.manual_task.id}/complete"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["completed"])

        self.assertTrue(
            UserPlatformTask.objects.filter(
                user=self.user,
                platform_task=self.manual_task,
                status=UserPlatformTask.Status.CLAIMED,
            ).exists()
        )

        resp = self.client.post(
            f"{BASE}/profile/me/platform-tasks/{self.manual_task.id}/complete"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already completed", resp.data["message"])

    def test_automatic_task_requires_claimable_before_claim(self):
        resp = self.client.post(
            f"{BASE}/profile/me/platform-tasks/{self.task1.id}/claim"
        )
        self.assertEqual(resp.status_code, 400)

    def test_get_user_badges_api(self):
        resp = self.client.get(f"{BASE}/profile/me/badges")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]), 0)

        UserBadge.objects.create(user=self.user, badge=self.badge_streak_7)

        resp = self.client.get(f"{BASE}/profile/me/badges")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]), 1)
        self.assertEqual(resp.data["data"][0]["badge"]["name"], "7-Day Streak")

    def test_get_user_streak_api(self):
        today = timezone.localdate()
        self.user.streak_count = 5
        self.user.last_active_date = today
        self.user.best_streak_count = 5
        self.user.save()

        resp = self.client.get(f"{BASE}/profile/me/streak")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]

        self.assertEqual(data["current_streak_count"], 5)
        self.assertTrue(data["is_streak_active"])
        self.assertEqual(data["best_streak"], 5)
        self.assertEqual(len(data["week"]["days"]), 7)
        self.assertEqual(data["milestone"]["interval_days"], 7)
        self.assertEqual(data["milestone"]["days_remaining"], 2)

    def test_profile_includes_earned_badges_and_stats(self):
        UserBadge.objects.create(user=self.user, badge=self.badge_rank_amateur)
        self.user.xp = 1500
        self.user.current_level = "amateur"
        self.user.streak_count = 3
        self.user.last_active_date = timezone.localdate()
        self.user.best_streak_count = 3
        self.user.save()

        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]

        self.assertEqual(data["xp"], 1500)
        self.assertEqual(data["current_level"], "amateur")
        self.assertEqual(data["streak_count"], 3)
        self.assertEqual(len(data["earned_badges"]), 1)
        self.assertEqual(data["earned_badges"][0]["badge"]["name"], "Amateur Rank")

    def test_admin_manage_gamification_settings(self):
        resp = self.admin_client.get(f"{BASE}/admin/platform-settings/gamification")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["xp_for_amateur"], 1000)

        payload = {
            "xp_for_amateur": 1200,
            "xp_for_senior": 6000,
            "xp_per_7_day_streak": 75,
        }
        resp = self.admin_client.patch(
            f"{BASE}/admin/platform-settings/gamification", payload, format="json"
        )
        self.assertEqual(resp.status_code, 200)

        config = SystemGamificationConfig.get_config()
        self.assertEqual(config.xp_for_amateur, 1200)
        self.assertEqual(config.xp_for_senior, 6000)
        self.assertEqual(config.xp_per_7_day_streak, 75)

    def test_admin_create_badge(self):
        payload = {
            "name": "Super Learner",
            "description": "Completed all learning tasks",
        }
        resp = self.admin_client.post(
            f"{BASE}/admin/gamification/badges", payload, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Badge.objects.filter(name="Super Learner").exists())
        self.assertIn("icon_url", resp.data["data"])
        self.assertIsNone(resp.data["data"]["icon_url"])

    def test_admin_create_badge_with_icon(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch

        icon = SimpleUploadedFile(
            "badge.png", BytesIO(b"fake-image").getvalue(), content_type="image/png"
        )
        with patch(
            "skiflux.views.gamification._schedule_badge_icon_upload"
        ) as mock_upload:
            resp = self.admin_client.post(
                f"{BASE}/admin/gamification/badges",
                {
                    "name": "Icon Badge",
                    "description": "Has an icon",
                    "icon": icon,
                },
                format="multipart",
            )
        self.assertEqual(resp.status_code, 201)
        badge = Badge.objects.get(name="Icon Badge")
        mock_upload.assert_called_once()
        self.assertEqual(mock_upload.call_args[0][0].id, badge.id)

    def test_admin_update_badge_icon_url(self):
        badge = Badge.objects.create(
            name="Updatable",
            description="Can be updated",
            icon_public_id="badges/updatable",
        )
        resp = self.admin_client.get(f"{BASE}/admin/gamification/badges/{badge.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.data["data"]["icon_url"])

        patch_resp = self.admin_client.patch(
            f"{BASE}/admin/gamification/badges/{badge.id}",
            {"description": "Updated description"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(patch_resp.data["data"]["description"], "Updated description")

    def test_admin_list_and_create_platform_tasks(self):
        self.assertEqual(PlatformTask.objects.count(), 3)

        resp = self.admin_client.get(f"{BASE}/admin/gamification/platform-tasks")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["data"]), 3)

        payload = {
            "title": "Flash Challenge",
            "description": "Complete before the timer runs out",
            "category": "flash",
            "trigger_type": "",
            "duration_minutes": 20,
            "xp_reward": 30,
            "skillcoin_reward": "30.00",
            "is_active": True,
        }
        resp = self.admin_client.post(
            f"{BASE}/admin/gamification/platform-tasks", payload, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(PlatformTask.objects.filter(title="Flash Challenge").exists())

    def test_admin_create_platform_task_with_action_type_alias(self):
        payload = {
            "title": "Subscribe Newsletter",
            "description": "Stay tuned to our notifications",
            "action_type": "link_social",
            "xp_reward": 50,
            "skillcoin_reward": "2.50",
            "is_active": True,
        }
        resp = self.admin_client.post(
            f"{BASE}/admin/gamification/platform-tasks", payload, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            PlatformTask.objects.filter(title="Subscribe Newsletter").exists()
        )

    def test_admin_update_and_deactivate_platform_task(self):
        resp = self.admin_client.patch(
            f"{BASE}/admin/gamification/platform-tasks/{self.manual_task.id}",
            {"title": "Follow Us on Instagram", "sort_order": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.manual_task.refresh_from_db()
        self.assertEqual(self.manual_task.title, "Follow Us on Instagram")

        resp = self.admin_client.delete(
            f"{BASE}/admin/gamification/platform-tasks/{self.manual_task.id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.manual_task.refresh_from_db()
        self.assertFalse(self.manual_task.is_active)

    def test_leaderboard_rankings(self):
        other_user = make_verified_user(email="other_learner@example.com")
        other_user.xp = 500
        other_user.current_level = "novice"
        other_user.save()

        self.user.xp = 100
        self.user.current_level = "novice"
        self.user.save()

        resp = self.client.get(f"{BASE}/me/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["rank"], 2)

        other_client = user_auth_client(other_user)
        resp2 = other_client.get(f"{BASE}/me/profile")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data["data"]["rank"], 1)
