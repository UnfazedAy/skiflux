import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from skiflux.models.content import (
    Episode,
    EpisodeComment,
    EpisodeNotInterested,
    EpisodePurchase,
    EpisodeRating,
    Follow,
)
from skiflux.models.wallet import SkillcoinTransaction, SystemFinancialConfig
from skiflux.services.wallet_service import WalletService

from .conftest import (
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class TrackViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )

    def test_track_view_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/track-view",
            {
                "episode_id": str(self.episode.id),
                "watch_duration_seconds": 120,
                "completed": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_track_view_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/episodes/track-view",
            {"episode_id": str(self.episode.id), "watch_duration_seconds": 10},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_track_view_missing_episode_id_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/track-view",
            {"watch_duration_seconds": 60},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class PurchaseEpisodeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        config = SystemFinancialConfig.get_config()
        config.episode_purchase_price_skillcoins = Decimal("10.00")
        config.save()
        self.paid_episode = make_episode(
            self.creator,
            self.season,
            title="Paid Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.PAID,
        )
        WalletService().credit_wallet(
            owner=self.user,
            amount=Decimal("100.00"),
            tx_type=SkillcoinTransaction.Type.ADMIN_ADJUSTMENT,
            description="Test credit",
            admin_user=self.creator,
        )
        self.free_episode = make_episode(
            self.creator,
            self.season,
            title="Free Ep",
            order=2,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )

    def test_purchase_paid_episode_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/purchase",
            {"episode_id": str(self.paid_episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            EpisodePurchase.objects.filter(
                user=self.user, episode=self.paid_episode
            ).exists()
        )

    def test_purchase_free_episode_returns_400(self):
        """Free episodes do not require purchase."""
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/purchase",
            {"episode_id": str(self.free_episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_purchase_episode_twice_returns_400(self):
        client = user_auth_client(self.user)
        client.post(
            f"{BASE}/episodes/purchase",
            {"episode_id": str(self.paid_episode.id)},
            format="json",
        )
        resp = client.post(
            f"{BASE}/episodes/purchase",
            {"episode_id": str(self.paid_episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_purchase_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/episodes/purchase",
            {"episode_id": str(self.paid_episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_purchase_nonexistent_episode_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/purchase",
            {"episode_id": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class RecommendationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        make_episode(
            self.creator,
            self.season,
            title="Public Ep",
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )

    def test_recommendations_returns_200(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/recommendations")
        self.assertEqual(resp.status_code, 200)

    def test_recommendations_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.get(f"{BASE}/episodes/recommendations")
        self.assertEqual(resp.status_code, 403)

    def test_get_season_episodes_nonexistent_returns_404(self):
        client = user_auth_client(self.user)
        fake_id = uuid.uuid4()
        resp = client.get(f"{BASE}/seasons/{fake_id}/episodes")
        self.assertEqual(resp.status_code, 404)

    def test_recommendations_includes_creator_object(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/recommendations")
        self.assertEqual(resp.status_code, 200)
        episodes = resp.data["data"]["results"]
        if episodes:
            creator = episodes[0]["creator"]
            self.assertIn("id", creator)
            self.assertIn("name", creator)
            self.assertIn("username", creator)
            self.assertIn("avatar_url", creator)
            self.assertIn("followers_count", creator)


class LikeEpisodeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )

    def test_like_episode_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/like",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["is_liked"])

    def test_unlike_episode_on_second_call(self):
        """Toggle: first call likes, second call unlikes."""
        client = user_auth_client(self.user)
        client.post(
            f"{BASE}/episodes/like",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        resp = client.post(
            f"{BASE}/episodes/like",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["is_liked"])

    def test_like_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/episodes/like",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class NotInterestedEpisodeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )

    def test_not_interested_episode_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/not-interested",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["removed"])
        self.assertFalse(resp.data["data"]["already_marked"])
        self.assertTrue(
            EpisodeNotInterested.objects.filter(
                user=self.user,
                episode=self.episode,
            ).exists()
        )

    def test_not_interested_is_idempotent(self):
        client = user_auth_client(self.user)
        client.post(
            f"{BASE}/episodes/not-interested",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        resp = client.post(
            f"{BASE}/episodes/not-interested",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["removed"])
        self.assertTrue(resp.data["data"]["already_marked"])
        self.assertEqual(
            EpisodeNotInterested.objects.filter(
                user=self.user,
                episode=self.episode,
            ).count(),
            1,
        )

    def test_not_interested_excludes_episode_from_recommendations(self):
        client = user_auth_client(self.user)
        client.post(
            f"{BASE}/episodes/not-interested",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        resp = client.get(f"{BASE}/episodes/recommendations")
        self.assertEqual(resp.status_code, 200)
        result_ids = {item["id"] for item in resp.data["data"]["results"]}
        self.assertNotIn(str(self.episode.id), result_ids)

    def test_not_interested_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/episodes/not-interested",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_not_interested_unpublished_episode_returns_400(self):
        draft_episode = make_episode(
            self.creator,
            self.season,
            order=2,
            status=Episode.Status.DRAFT,
            access_type=Episode.AccessType.FREE,
        )
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/not-interested",
            {"episode_id": str(draft_episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class SaveEpisodeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )

    def test_save_episode_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/save",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["is_saved"])

    def test_unsave_episode_on_second_call(self):
        """Toggle: first call saves, second call unsaves."""
        client = user_auth_client(self.user)
        client.post(
            f"{BASE}/episodes/save",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        resp = client.post(
            f"{BASE}/episodes/save",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertFalse(resp.data["data"]["is_saved"])

    def test_save_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/episodes/save",
            {"episode_id": str(self.episode.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class CommentTests(TestCase):
    def setUp(self):
        patcher = patch("skiflux.services.content_service.moderate_comment_task.delay")
        self.mock_delay = patcher.start()
        self.addCleanup(patcher.stop)
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )

    def test_add_comment_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/comment",
            {
                "episode_id": str(self.episode.id),
                "text": "Great episode!",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_add_empty_comment_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/comment",
            {"episode_id": str(self.episode.id), "text": ""},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_get_comments_for_episode(self):
        client = user_auth_client(self.user)
        client.post(
            f"{BASE}/episodes/comment",
            {"episode_id": str(self.episode.id), "text": "Nice!"},
            format="json",
        )
        resp = client.get(f"{BASE}/episodes/{self.episode.id}/comments")
        self.assertEqual(resp.status_code, 200)

    def test_add_comment_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/episodes/comment",
            {"episode_id": str(self.episode.id), "text": "Hello"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_get_comments_returns_paginated_response(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/{self.episode.id}/comments")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("results", data)


class CommentInteractionTests(TestCase):
    def setUp(self):
        patcher = patch("skiflux.services.content_service.moderate_comment_task.delay")
        self.mock_delay = patcher.start()
        self.addCleanup(patcher.stop)
        cache.clear()
        self.user = make_verified_user()
        self.other_user = make_verified_user(email="other@example.com")
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )
        self.comment = EpisodeComment.objects.create(
            user=self.user,
            episode=self.episode,
            text="Original comment",
        )

    def test_like_comment_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/comments/like",
            {"comment_id": self.comment.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["is_liked"])
        self.assertTrue(self.comment.liked_by.filter(id=self.user.id).exists())

    def test_unlike_comment_on_second_call(self):
        client = user_auth_client(self.user)
        client.post(
            f"{BASE}/comments/like",
            {"comment_id": self.comment.id},
            format="json",
        )
        resp = client.post(
            f"{BASE}/comments/like",
            {"comment_id": self.comment.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["is_liked"])

    def test_delete_comment_success(self):
        client = user_auth_client(self.user)
        resp = client.delete(f"{BASE}/comments/{self.comment.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(EpisodeComment.objects.filter(id=self.comment.id).exists())

    def test_delete_comment_non_owner_returns_403(self):
        client = user_auth_client(self.other_user)
        resp = client.delete(f"{BASE}/comments/{self.comment.id}/")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(EpisodeComment.objects.filter(id=self.comment.id).exists())

    def test_edit_comment_success(self):
        client = user_auth_client(self.user)
        resp = client.patch(
            f"{BASE}/comments/{self.comment.id}/",
            {"text": "Updated comment"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.text, "Updated comment")
        self.assertEqual(resp.data["data"]["text"], "Updated comment")

    def test_edit_comment_non_owner_returns_403(self):
        client = user_auth_client(self.other_user)
        resp = client.patch(
            f"{BASE}/comments/{self.comment.id}/",
            {"text": "Hacked"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.text, "Original comment")

    def test_reply_to_comment_success(self):
        client = user_auth_client(self.other_user)
        resp = client.post(
            f"{BASE}/comments/{self.comment.id}/reply/",
            {"text": "Nice point!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        reply = EpisodeComment.objects.get(text="Nice point!")
        self.assertEqual(reply.parent_id, self.comment.id)
        self.assertEqual(reply.episode_id, self.episode.id)

    def test_get_comments_includes_replies(self):
        EpisodeComment.objects.create(
            user=self.other_user,
            episode=self.episode,
            text="A reply",
            parent=self.comment,
        )
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/{self.episode.id}/comments")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["replies"]), 1)
        self.assertEqual(results[0]["replies"][0]["text"], "A reply")

    def test_like_comment_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/comments/like",
            {"comment_id": self.comment.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class ToggleFollowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()

    def test_toggle_follow_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/creators/{self.creator.id}/follow/",
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["is_following"])
        self.assertEqual(str(resp.data["data"]["creator_id"]), str(self.creator.id))
        self.assertEqual(resp.data["data"]["followers_count"], 1)
        self.assertTrue(
            Follow.objects.filter(follower=self.user, creator=self.creator).exists()
        )

    def test_toggle_follow_second_call_unfollows(self):
        client = user_auth_client(self.user)
        client.post(f"{BASE}/creators/{self.creator.id}/follow/", format="json")
        resp = client.post(
            f"{BASE}/creators/{self.creator.id}/follow/",
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["is_following"])
        self.assertEqual(resp.data["data"]["followers_count"], 0)
        self.assertFalse(
            Follow.objects.filter(follower=self.user, creator=self.creator).exists()
        )

    def test_toggle_follow_nonexistent_creator_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(f"{BASE}/creators/{uuid.uuid4()}/follow/", format="json")

        self.assertEqual(resp.status_code, 400)

    def test_toggle_follow_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/creators/{self.creator.id}/follow/",
            format="json",
        )

        self.assertEqual(resp.status_code, 403)


class CreatorPublicProfileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator(
            username="publiccreator",
            bio="Creator bio",
        )
        self.client = user_auth_client(self.user)

    def test_get_creator_profile_success(self):
        resp = self.client.get(f"{BASE}/creators/{self.creator.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        for field in [
            "id",
            "username",
            "first_name",
            "last_name",
            "display_name",
            "avatar_url",
            "bio",
            "skillworld",
            "followers_count",
            "is_following",
        ]:
            self.assertIn(field, data)
        self.assertNotIn("email", data)
        self.assertEqual(data["username"], "publiccreator")
        self.assertFalse(data["is_following"])
        self.assertEqual(data["followers_count"], 0)

    def test_get_creator_profile_is_following(self):
        Follow.objects.create(follower=self.user, creator=self.creator)
        resp = self.client.get(f"{BASE}/creators/{self.creator.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["is_following"])
        self.assertEqual(resp.data["data"]["followers_count"], 1)

    def test_get_creator_profile_not_found(self):
        resp = self.client.get(f"{BASE}/creators/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)

    def test_get_deactivated_creator_returns_404(self):
        from skiflux.models.admin_user import AdminUser

        self.creator.status = AdminUser.Status.DEACTIVATED
        self.creator.save(update_fields=["status"])
        resp = self.client.get(f"{BASE}/creators/{self.creator.id}")
        self.assertEqual(resp.status_code, 404)


class RateEpisodeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.PAID,
        )
        EpisodePurchase.objects.create(
            user=self.user,
            episode=self.episode,
            amount_paid=SystemFinancialConfig.get_config().episode_purchase_price_skillcoins,
        )

    def test_rate_episode_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 5, "review": "Excellent episode."},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["episode_id"], str(self.episode.id))
        self.assertEqual(resp.data["data"]["score"], 5)
        self.assertEqual(resp.data["data"]["review"], "Excellent episode.")
        self.assertTrue(
            EpisodeRating.objects.filter(
                user=self.user,
                episode=self.episode,
                score=5,
            ).exists()
        )

    def test_rate_episode_updates_existing_rating(self):
        EpisodeRating.objects.create(
            user=self.user,
            episode=self.episode,
            score=3,
            review="Good.",
        )
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 4, "review": "Even better now."},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["score"], 4)
        self.assertEqual(resp.data["data"]["review"], "Even better now.")
        self.assertEqual(
            EpisodeRating.objects.filter(user=self.user, episode=self.episode).count(),
            1,
        )

    def test_rate_episode_requires_purchase(self):
        other_user = make_verified_user(email="other@example.com")
        client = user_auth_client(other_user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 4},
            format="json",
        )

        self.assertEqual(resp.status_code, 403)

    def test_rate_episode_invalid_score_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 6},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_rate_episode_nonexistent_episode_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{uuid.uuid4()}/rate/",
            {"score": 4},
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )
        self.assertEqual(resp.status_code, 400)


class ToggleFollowTestsSecond(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()

    def test_toggle_follow_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/creators/{self.creator.id}/follow/",
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["data"]["is_following"])
        self.assertEqual(str(resp.data["data"]["creator_id"]), str(self.creator.id))
        self.assertEqual(resp.data["data"]["followers_count"], 1)
        self.assertTrue(
            Follow.objects.filter(follower=self.user, creator=self.creator).exists()
        )

    def test_toggle_follow_second_call_unfollows(self):
        client = user_auth_client(self.user)
        client.post(f"{BASE}/creators/{self.creator.id}/follow/", format="json")
        resp = client.post(
            f"{BASE}/creators/{self.creator.id}/follow/",
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["data"]["is_following"])
        self.assertEqual(resp.data["data"]["followers_count"], 0)
        self.assertFalse(
            Follow.objects.filter(follower=self.user, creator=self.creator).exists()
        )

    def test_toggle_follow_nonexistent_creator_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(f"{BASE}/creators/{uuid.uuid4()}/follow/", format="json")

        self.assertEqual(resp.status_code, 400)

    def test_toggle_follow_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/creators/{self.creator.id}/follow/",
            format="json",
        )

        self.assertEqual(resp.status_code, 403)


class RateEpisodeTestsSecond(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.PAID,
        )
        EpisodePurchase.objects.create(
            user=self.user,
            episode=self.episode,
            amount_paid=SystemFinancialConfig.get_config().episode_purchase_price_skillcoins,
        )

    def test_rate_episode_success(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 5, "review": "Excellent episode."},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["episode_id"], str(self.episode.id))
        self.assertEqual(resp.data["data"]["score"], 5)
        self.assertEqual(resp.data["data"]["review"], "Excellent episode.")
        self.assertTrue(
            EpisodeRating.objects.filter(
                user=self.user,
                episode=self.episode,
                score=5,
            ).exists()
        )

    def test_rate_episode_updates_existing_rating(self):
        EpisodeRating.objects.create(
            user=self.user,
            episode=self.episode,
            score=3,
            review="Good.",
        )
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 4, "review": "Even better now."},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["score"], 4)
        self.assertEqual(resp.data["data"]["review"], "Even better now.")
        self.assertEqual(
            EpisodeRating.objects.filter(user=self.user, episode=self.episode).count(),
            1,
        )

    def test_rate_episode_requires_purchase(self):
        other_user = make_verified_user(email="other@example.com")
        client = user_auth_client(other_user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 4},
            format="json",
        )

        self.assertEqual(resp.status_code, 403)

    def test_rate_episode_invalid_score_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 6},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_rate_episode_nonexistent_episode_returns_400(self):
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/episodes/{uuid.uuid4()}/rate/",
            {"score": 4},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)

    def test_rate_episode_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/episodes/{self.episode.id}/rate/",
            {"score": 5},
            format="json",
        )

        self.assertEqual(resp.status_code, 403)


class GetFollowedCreatorsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator1 = make_creator(email="creator1@example.com", username="creator1")
        self.creator2 = make_creator(email="creator2@example.com", username="creator2")
        self.creator3 = make_creator(email="creator3@example.com", username="creator3")

        # user follows creator1 and creator2
        Follow.objects.create(follower=self.user, creator=self.creator1)
        Follow.objects.create(follower=self.user, creator=self.creator2)

    def test_get_followed_creators_success(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/creators/following/")

        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertEqual(data["count"], 2)
        results = data["results"]
        self.assertEqual(len(results), 2)

        creator_ids = [c["id"] for c in results]
        self.assertIn(str(self.creator1.id), creator_ids)
        self.assertIn(str(self.creator2.id), creator_ids)
        self.assertNotIn(str(self.creator3.id), creator_ids)

    def test_get_followed_creators_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.get(f"{BASE}/creators/following/")
        self.assertEqual(resp.status_code, 403)


class GetLatestFollowedEpisodesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user()
        self.creator1 = make_creator(email="creator1@example.com", username="creator1")
        self.creator2 = make_creator(email="creator2@example.com", username="creator2")
        self.creator3 = make_creator(email="creator3@example.com", username="creator3")

        # user follows creator1 and creator2
        Follow.objects.create(follower=self.user, creator=self.creator1)
        Follow.objects.create(follower=self.user, creator=self.creator2)

        self.season1 = make_season(self.creator1, title="Season C1")
        self.season2 = make_season(self.creator2, title="Season C2")
        self.season3 = make_season(self.creator3, title="Season C3")

        # Episodes for creator1 (followed)
        self.ep1 = make_episode(
            self.creator1, self.season1, order=1, status=Episode.Status.PUBLISHED
        )
        self.ep2 = make_episode(
            self.creator1, self.season1, order=2, status=Episode.Status.DRAFT
        )

        # Episodes for creator2 (followed)
        self.ep3 = make_episode(
            self.creator2, self.season2, order=1, status=Episode.Status.PUBLISHED
        )

        # Episodes for creator3 (not followed)
        self.ep4 = make_episode(
            self.creator3, self.season3, order=1, status=Episode.Status.PUBLISHED
        )

    def test_get_latest_followed_episodes_success(self):
        client = user_auth_client(self.user)
        resp = client.get(f"{BASE}/episodes/following/")

        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertEqual(
            data["count"], 2
        )  # ep1 and ep3 are published and from followed creators
        results = data["results"]
        self.assertEqual(len(results), 2)

        episode_ids = [ep["id"] for ep in results]
        self.assertIn(str(self.ep1.id), episode_ids)
        self.assertIn(str(self.ep3.id), episode_ids)
        self.assertNotIn(str(self.ep2.id), episode_ids)  # Draft
        self.assertNotIn(str(self.ep4.id), episode_ids)  # Creator not followed

    def test_get_latest_followed_episodes_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.get(f"{BASE}/episodes/following/")
        self.assertEqual(resp.status_code, 403)
