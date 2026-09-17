from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from skiflux.models import UserDevice
from skiflux.models.notification_preference import UserNotificationPreferences
from skiflux.services.notification_service import NotificationService

from tests.api_v1.conftest import make_creator, make_verified_user


class SendPushForEventPreferenceTests(TestCase):
    """send_push_for_event honors UserNotificationPreferences for learners."""

    def setUp(self):
        cache.clear()
        self.service = NotificationService()
        self.user = make_verified_user(email="prefs-push@example.com")
        UserDevice.objects.create(
            user=self.user,
            token="fcm_test_token_prefs_push_12345",
            platform=UserDevice.Platform.ANDROID,
            is_active=True,
        )
        self.prefs = UserNotificationPreferences.get_or_create_for_user(self.user)

    @patch("skiflux.services.notification_service.send_push_notification_task")
    def test_push_sent_when_preference_enabled(self, mock_task):
        self.prefs.task_updates = True
        self.prefs.save(update_fields=["task_updates"])

        sent = self.service.send_push_for_event(
            user=self.user,
            event_type="task_approved_with_coins",
        )

        self.assertEqual(sent, 1)
        mock_task.delay.assert_called_once()

    @patch("skiflux.services.notification_service.send_push_notification_task")
    def test_push_suppressed_when_preference_disabled(self, mock_task):
        self.prefs.task_updates = False
        self.prefs.save(update_fields=["task_updates"])

        sent = self.service.send_push_for_event(
            user=self.user,
            event_type="task_approved_with_coins",
        )

        self.assertEqual(sent, 0)
        mock_task.delay.assert_not_called()

    @patch("skiflux.services.notification_service.send_push_notification_task")
    def test_unknown_event_type_not_gated_by_preferences(self, mock_task):
        self.prefs.task_updates = False
        self.prefs.new_episodes = False
        self.prefs.save(update_fields=["task_updates", "new_episodes"])

        sent = self.service.send_push_for_event(
            user=self.user,
            event_type="we_miss_you",
        )

        self.assertEqual(sent, 1)
        mock_task.delay.assert_called_once()

    @patch("skiflux.services.notification_service.send_push_notification_task")
    def test_admin_push_not_gated_by_user_preferences(self, mock_task):
        admin = make_creator(email="creator-prefs-push@example.com")
        UserDevice.objects.create(
            admin_user=admin,
            token="fcm_test_token_admin_prefs_12345",
            platform=UserDevice.Platform.ANDROID,
            is_active=True,
        )

        sent = self.service.send_push_for_event(
            admin_user=admin,
            event_type="task_submission_received",
        )

        self.assertEqual(sent, 1)
        mock_task.delay.assert_called_once()

    @patch("skiflux.services.notification_service.send_push_notification_task")
    def test_comment_likes_preference_maps_correctly(self, mock_task):
        self.prefs.comment_likes = False
        self.prefs.save(update_fields=["comment_likes"])

        sent = self.service.send_push_for_event(
            user=self.user,
            event_type="comment_liked",
        )

        self.assertEqual(sent, 0)
        mock_task.delay.assert_not_called()
