from django.core.cache import cache
from django.test import TestCase

from skiflux.models.platform_settings import (
    SystemContentConfig,
    SystemFeatureFlagConfig,
    SystemNotificationConfig,
    SystemSecurityConfig,
)

from .conftest import admin_auth_client, make_admin_with_role, make_super_admin

BASE = "/api/v1"


class PlatformContentSettingsAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.super_client = admin_auth_client(self.super_admin)
        self.normal_admin, _ = make_admin_with_role(
            [],
            email="platformadmin@skiflux.com",
        )
        self.normal_client = admin_auth_client(self.normal_admin)

    def test_super_admin_can_retrieve_content_settings(self):
        resp = self.super_client.get(f"{BASE}/admin/platform/content-config")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("max_video_size_mb", resp.data["data"])
        self.assertIn("allowed_video_formats", resp.data["data"])

    def test_super_admin_can_update_content_settings(self):
        resp = self.super_client.patch(
            f"{BASE}/admin/platform/content-config",
            {
                "max_video_size_mb": 150,
                "max_episodes_per_season": 20,
                "allowed_video_formats": ["mp4", "webm"],
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        config = SystemContentConfig.get_config()
        self.assertEqual(config.max_video_size_mb, 150)
        self.assertEqual(config.max_episodes_per_season, 20)
        self.assertEqual(config.allowed_video_formats, ["mp4", "webm"])

    def test_non_super_admin_cannot_update_content_settings(self):
        resp = self.normal_client.patch(
            f"{BASE}/admin/platform/content-config",
            {"max_video_size_mb": 200},
            format="json",
        )

        self.assertEqual(resp.status_code, 403)

    def test_patch_with_invalid_values_returns_bad_request(self):
        resp = self.super_client.patch(
            f"{BASE}/admin/platform/content-config",
            {"max_video_size_mb": 0},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("max_video_size_mb", resp.data["message"])

    def test_super_admin_can_retrieve_notification_settings(self):
        resp = self.super_client.get(f"{BASE}/admin/platform/notification-config")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("episode_approved", resp.data["data"])
        self.assertIn("streak_reminder", resp.data["data"])

    def test_super_admin_can_update_notification_settings(self):
        resp = self.super_client.patch(
            f"{BASE}/admin/platform/notification-config",
            {"streak_reminder": True},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        config = SystemNotificationConfig.get_config()
        self.assertTrue(config.streak_reminder)

    def test_super_admin_can_retrieve_security_settings(self):
        resp = self.super_client.get(f"{BASE}/admin/platform/security-config")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("session_timeout_minutes", resp.data["data"])
        self.assertIn("require_2fa_for_admins", resp.data["data"])

    def test_super_admin_can_update_security_settings(self):
        resp = self.super_client.patch(
            f"{BASE}/admin/platform/security-config",
            {"session_timeout_minutes": 90},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        config = SystemSecurityConfig.get_config()
        self.assertEqual(config.session_timeout_minutes, 90)

    def test_super_admin_can_retrieve_feature_flag_settings(self):
        resp = self.super_client.get(f"{BASE}/admin/platform/feature-flag-config")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("leaderboard", resp.data["data"])
        self.assertIn("maintenance_mode", resp.data["data"])

    def test_super_admin_can_update_feature_flag_settings(self):
        resp = self.super_client.patch(
            f"{BASE}/admin/platform/feature-flag-config",
            {"maintenance_mode": True},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        config = SystemFeatureFlagConfig.get_config()
        self.assertTrue(config.maintenance_mode)
