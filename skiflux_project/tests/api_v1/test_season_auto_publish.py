"""Season auto-publish and deferred follower notifications."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.content import Episode, Follow
from skiflux.services.season_publish_service import SeasonPublishService
from skiflux.services.studio_service import StudioService

from .conftest import (
    admin_auth_client,
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
)

BASE = "/api/v1"


class SeasonAutoPublishNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = make_creator()
        self.follower = make_verified_user(email="follower@example.com")
        Follow.objects.create(follower=self.follower, creator=self.creator)
        self.client = admin_auth_client(self.creator)
        self.season = make_season(self.creator, title="Notify Season")

    @patch("skiflux.services.studio_service.NotificationService")
    def test_create_season_does_not_notify_followers(self, mock_notif_cls):
        StudioService().create_season(
            admin=self.creator,
            title="Brand New Season",
            description="Desc",
            skillworld="design",
        )
        mock_notif_cls.return_value.create_notification.assert_not_called()
        mock_notif_cls.return_value.send_push_for_event.assert_not_called()

    @patch.object(SeasonPublishService, "_notify_followers_new_season")
    def test_auto_publish_notifies_followers_once(self, mock_notify):
        episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        service = SeasonPublishService()
        self.assertTrue(service.maybe_publish_season_for_episode(episode))
        mock_notify.assert_called_once()

        ep2 = make_episode(
            self.creator,
            self.season,
            order=2,
            status=Episode.Status.PUBLISHED,
        )
        self.assertFalse(service.maybe_publish_season_for_episode(ep2))
        mock_notify.assert_called_once()
