from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from skiflux.models.notification import Notification
from skiflux.models.role import Permission

from .conftest import (
    admin_auth_client,
    make_admin_with_role,
    make_super_admin,
    make_verified_user,
)

BASE = "/api/v1"


def _create_notification(
    user,
    *,
    title="Weekend Challenge Reminder",
    body="Don't forget to complete your weekend challenge!",
    delivery_channel=Notification.DeliveryChannel.FOREGROUND,
    delivery_status=Notification.DeliveryStatus.SENT,
    audience="All users",
    scheduled_at=None,
):
    return Notification.objects.create(
        user=user,
        type=Notification.Type.TASK_REMINDER,
        title=title,
        body=body,
        delivery_channel=delivery_channel,
        delivery_status=delivery_status,
        audience=audience,
        scheduled_at=scheduled_at,
    )


class AdminNotificationStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.user = make_verified_user(email="notify-user@skiflux.com")

    def test_stats_returns_aggregate_counts(self):
        _create_notification(
            self.user, delivery_channel=Notification.DeliveryChannel.FOREGROUND
        )
        _create_notification(
            self.user,
            title="Streak Recovery Window",
            body="You still have time to recover your streak.",
            delivery_channel=Notification.DeliveryChannel.FOREGROUND,
        )
        _create_notification(
            self.user,
            title="Push Reminder",
            body="Open the app to continue learning.",
            delivery_channel=Notification.DeliveryChannel.BACKGROUND,
        )
        _create_notification(
            self.user,
            title="Scheduled Announcement",
            body="Coming soon.",
            delivery_status=Notification.DeliveryStatus.PENDING,
            scheduled_at=timezone.now() + timedelta(days=1),
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/notifications/stats")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        data = resp.data["data"]
        self.assertEqual(data["total_sent"], 3)
        self.assertEqual(data["total_foreground"], 2)
        self.assertEqual(data["total_background"], 1)
        self.assertEqual(data["scheduled_pending"], 1)

    def test_admin_with_analytics_view_can_read_stats(self):
        admin, _ = make_admin_with_role([Permission.ANALYTICS_VIEW])
        client = admin_auth_client(admin)

        resp = client.get(f"{BASE}/admin/notifications/stats")

        self.assertEqual(resp.status_code, 200)

    def test_admin_without_analytics_view_is_blocked(self):
        admin, _ = make_admin_with_role([Permission.CONTENT_VIEW])
        client = admin_auth_client(admin)

        resp = client.get(f"{BASE}/admin/notifications/stats")

        self.assertEqual(resp.status_code, 403)


class AdminNotificationHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.user = make_verified_user(email="history-user@skiflux.com")

    def test_history_returns_grouped_notification_rows(self):
        send_time = timezone.now() - timedelta(hours=2)
        for _ in range(3):
            notification = _create_notification(
                self.user,
                title="Weekend Challenge Reminder",
                body="Complete your challenge this weekend.",
                delivery_channel=Notification.DeliveryChannel.FOREGROUND,
                audience="All users",
            )
            Notification.objects.filter(id=notification.id).update(created_at=send_time)

        _create_notification(
            self.user,
            title="Streak Recovery Window",
            body="Recover your streak before midnight.",
            delivery_channel=Notification.DeliveryChannel.BACKGROUND,
            audience="Inactive 5+ days",
        )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/notifications/history")

        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)

        by_title = {row["title"]: row for row in data["results"]}
        grouped = by_title["Weekend Challenge Reminder"]
        self.assertEqual(grouped["message"], "Complete your challenge this weekend.")
        self.assertEqual(grouped["type"], "foreground")
        self.assertEqual(grouped["audience"], "All users")
        self.assertEqual(grouped["status"], "sent")
        self.assertEqual(grouped["recipient_count"], 3)

    def test_history_supports_type_filters(self):
        _create_notification(
            self.user,
            delivery_channel=Notification.DeliveryChannel.FOREGROUND,
        )
        _create_notification(
            self.user,
            title="Background Push",
            body="System tray notification.",
            delivery_channel=Notification.DeliveryChannel.BACKGROUND,
        )
        _create_notification(
            self.user,
            title="Pending Daily",
            body="Scheduled for tomorrow.",
            delivery_status=Notification.DeliveryStatus.PENDING,
            scheduled_at=timezone.now() + timedelta(days=1),
        )

        client = admin_auth_client(self.super_admin)

        foreground_resp = client.get(
            f"{BASE}/admin/notifications/history?type=foreground"
        )
        self.assertEqual(foreground_resp.data["data"]["count"], 1)
        self.assertEqual(
            foreground_resp.data["data"]["results"][0]["type"], "foreground"
        )

        background_resp = client.get(
            f"{BASE}/admin/notifications/history?type=background"
        )
        self.assertEqual(background_resp.data["data"]["count"], 1)
        self.assertEqual(
            background_resp.data["data"]["results"][0]["type"], "background"
        )

        scheduled_resp = client.get(
            f"{BASE}/admin/notifications/history?type=scheduled"
        )
        self.assertEqual(scheduled_resp.data["data"]["count"], 1)
        self.assertEqual(scheduled_resp.data["data"]["results"][0]["status"], "pending")

    def test_history_supports_pagination(self):
        for index in range(3):
            _create_notification(
                self.user,
                title=f"Notification {index}",
                body=f"Message {index}",
            )

        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/notifications/history?limit=2&page=1")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 3)
        self.assertEqual(len(resp.data["data"]["results"]), 2)
        self.assertIsNotNone(resp.data["data"]["next"])

    def test_admin_without_analytics_view_is_blocked(self):
        admin, _ = make_admin_with_role([Permission.CONTENT_VIEW])
        client = admin_auth_client(admin)

        resp = client.get(f"{BASE}/admin/notifications/history")

        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_request_is_blocked(self):
        resp = APIClient().get(f"{BASE}/admin/notifications/history")

        self.assertEqual(resp.status_code, 403)
