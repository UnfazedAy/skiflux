"""
Creator Studio Tests
Covers: creator registration, email verification, season/episode CRUD,
        OTP resend, and permission guards on creator-only endpoints.
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from skiflux.models import AdminUser
from skiflux.models.content import Episode, EpisodeTask, Season
from skiflux.utils.auth import set_creator_verification_otp

from .conftest import (
    admin_auth_client,
    make_creator,
    make_episode,
    make_season,
)

BASE = "/api/v1"


class CreatorRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.email_patcher = patch("skiflux.tasks.auth.requests.post")
        mock_post = self.email_patcher.start()
        mock_post.return_value = MagicMock(
            status_code=201, raise_for_status=lambda: None
        )

    def tearDown(self):
        self.email_patcher.stop()

    def _register(self, email="creator@studio.com", username="creator1"):
        client = APIClient()
        return client.post(
            f"{BASE}/creator/register",
            {
                "first_name": "Creative",
                "last_name": "Person",
                "email": email,
                "username": username,
                "password": "CreatorPass1!",
                "password_confirm": "CreatorPass1!",
            },
            format="json",
        )

    def test_creator_registration_success_returns_201(self):
        resp = self._register()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            AdminUser.objects.filter(
                email="creator@studio.com",
                role_type=AdminUser.RoleType.CREATOR,
            ).exists()
        )

    def test_creator_registration_duplicate_email_returns_400(self):
        self._register(email="dup@studio.com")
        resp = self._register(email="dup@studio.com", username="different")
        self.assertEqual(resp.status_code, 400)

    def test_creator_registration_duplicate_username_returns_400(self):
        self._register(email="a@studio.com", username="samename")
        resp = self._register(email="b@studio.com", username="samename")
        self.assertEqual(resp.status_code, 400)

    def test_creator_registration_username_starting_with_digit_returns_400(self):
        resp = self._register(email="digit@studio.com", username="1badname")
        self.assertEqual(resp.status_code, 400)

    def test_creator_registration_missing_fields_returns_400(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/creator/register",
            {"email": "incomplete@studio.com"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class CreatorEmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.email_patcher = patch("skiflux.tasks.auth.requests.post")
        mock_post = self.email_patcher.start()
        mock_post.return_value = MagicMock(
            status_code=201, raise_for_status=lambda: None
        )

    def tearDown(self):
        self.email_patcher.stop()

    def test_verify_creator_email_success(self):
        creator = make_creator(
            email="verifyc@studio.com",
            username="verifyc",
        )
        creator.is_verified = False
        creator.save()
        set_creator_verification_otp(creator.email, "112233")
        client = APIClient()
        resp = client.post(
            f"{BASE}/creator/verify-email",
            {"email": creator.email, "otp": "112233"},
        )
        self.assertEqual(resp.status_code, 200)
        creator.refresh_from_db()
        self.assertTrue(creator.is_verified)

    def test_verify_creator_email_wrong_otp(self):
        creator = make_creator(
            email="wrongotp@studio.com",
            username="wrongotpc",
        )
        creator.is_verified = False
        creator.save()
        set_creator_verification_otp(creator.email, "999999")
        client = APIClient()
        resp = client.post(
            f"{BASE}/creator/verify-email",
            {"email": creator.email, "otp": "000000"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_resend_creator_otp_success(self):
        creator = make_creator(
            email="resendotp@studio.com",
            username="resendotpc",
        )
        creator.is_verified = False
        creator.save()
        client = APIClient()
        resp = client.post(
            f"{BASE}/creator/resend-otp",
            {"email": creator.email},
        )
        self.assertEqual(resp.status_code, 200)


class SeasonManagementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = make_creator()
        self.client = admin_auth_client(self.creator)

    def test_create_season_success(self):
        resp = self.client.post(
            f"{BASE}/creator/create-season",
            {
                "title": "Season Alpha",
                "description": "First season",
                "skillworld": "design",
                "price": "0.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            Season.objects.filter(creator=self.creator, title="Season Alpha").exists()
        )

    def test_create_season_missing_title_returns_400(self):
        resp = self.client.post(
            f"{BASE}/creator/create-season",
            {"skillworld": "design"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_seasons_returns_200(self):
        make_season(self.creator, title="S1")
        make_season(self.creator, title="S2")
        resp = self.client.get(f"{BASE}/creator/list-seasons")
        self.assertEqual(resp.status_code, 200)

    def test_list_seasons_only_returns_own_seasons(self):
        other_creator = make_creator(email="other@studio.com", username="othercreator")
        make_season(other_creator, title="Other Season")
        make_season(self.creator, title="My Season")
        resp = self.client.get(f"{BASE}/creator/list-seasons")
        self.assertEqual(resp.status_code, 200)
        titles = [s["title"] for s in resp.data["data"]]
        self.assertIn("My Season", titles)
        self.assertNotIn("Other Season", titles)

    def test_unauthenticated_cannot_create_season(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/creator/create-season",
            {"title": "Sneaky Season", "skillworld": "code"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class EpisodeManagementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = make_creator()
        self.client = admin_auth_client(self.creator)
        self.season = make_season(self.creator)

    @patch("skiflux.utils.media.send_app_email_task.apply_async")
    @patch(
        "skiflux.tasks.content.cloudinary.uploader.upload",
        return_value={"public_id": "test_vid", "duration": 60},
    )
    @patch(
        "skiflux.services.studio_service.upload_to_minio",
        return_value="skiflux_episodes/fake-key.mp4",
    )
    def test_create_episode_success(self, mock_minio, mock_upload, mock_email):
        from django.core.files.uploadedfile import SimpleUploadedFile

        video = SimpleUploadedFile("video.mp4", b"content", content_type="video/mp4")
        resp = self.client.post(
            f"{BASE}/creator/create-episode",
            {
                "season_id": str(self.season.id),
                "title": "Ep 1",
                "description": "Great episode",
                "order": 1,
                "access_type": "free",
                "video_file": video,
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        episode = Episode.objects.get(creator=self.creator, title="Ep 1")
        self.assertEqual(episode.status, Episode.Status.PROCESSING)

    @patch("skiflux.utils.media.send_app_email_task.apply_async")
    @patch(
        "skiflux.tasks.content.cloudinary.uploader.upload",
        return_value={"public_id": "test_vid", "duration": 60},
    )
    @patch(
        "skiflux.services.studio_service.upload_to_minio",
        return_value="skiflux_episodes/fake-key.mp4",
    )
    def test_create_episode_duplicate_order_returns_400(
        self, mock_minio, mock_upload, mock_email
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        video = SimpleUploadedFile("video.mp4", b"content", content_type="video/mp4")
        payload = {
            "season_id": str(self.season.id),
            "title": "Ep A",
            "description": "First",
            "order": 3,
            "access_type": "free",
            "video_file": video,
        }
        resp1 = self.client.post(
            f"{BASE}/creator/create-episode", payload, format="multipart"
        )
        self.assertEqual(resp1.status_code, 201)
        payload["title"] = "Ep B"
        resp2 = self.client.post(
            f"{BASE}/creator/create-episode", payload, format="multipart"
        )
        self.assertEqual(resp2.status_code, 400)

    def test_create_episode_missing_fields_returns_400(self):
        resp = self.client.post(
            f"{BASE}/creator/create-episode",
            {"title": "Missing Season"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_episodes_returns_200(self):
        make_episode(self.creator, self.season, title="Ep A", order=1)
        make_episode(self.creator, self.season, title="Ep B", order=2)
        resp = self.client.get(f"{BASE}/creator/list-episodes")
        self.assertEqual(resp.status_code, 200)

    def test_list_episodes_only_returns_own(self):
        other = make_creator(email="other2@studio.com", username="other2creator")
        other_season = make_season(other, title="Other Season")
        make_episode(other, other_season, title="Other Ep", order=1)
        make_episode(self.creator, self.season, title="My Ep", order=1)
        resp = self.client.get(f"{BASE}/creator/list-episodes")
        titles = [e["title"] for e in resp.data["data"]]
        self.assertIn("My Ep", titles)
        self.assertNotIn("Other Ep", titles)

    def test_episode_order_constraint_enforced(self):
        """Order must be between 1 and 10."""
        resp = self.client.post(
            f"{BASE}/creator/create-episode",
            {
                "season_id": str(self.season.id),
                "title": "Bad Order",
                "description": "Out of range",
                "order": 11,
                "access_type": "free",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_attach_task_to_own_episode_returns_201(self):
        episode = make_episode(
            self.creator,
            self.season,
            title="Task Ep",
            order=5,
            status=Episode.Status.PROCESSING,
        )
        resp = self.client.post(
            f"{BASE}/creator/episode/{episode.id}/attach-task",
            {
                "project_task": {
                    "task_brief": "Build a project",
                    "accepted_proof_types": ["image"],
                    "completion_criteria": {"min_score": 80},
                }
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(EpisodeTask.objects.filter(episode=episode).exists())

    def test_attach_task_to_other_creator_episode_returns_400(self):
        other = make_creator(email="othertask@studio.com", username="othertaskcreator")
        other_season = make_season(other, title="Other Season Tasks")
        episode = make_episode(
            other,
            other_season,
            title="Other Task Ep",
            order=1,
            status=Episode.Status.PROCESSING,
        )
        resp = self.client.post(
            f"{BASE}/creator/episode/{episode.id}/attach-task",
            {
                "project_task": {
                    "task_brief": "Sneaky task",
                    "accepted_proof_types": [],
                }
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unverified_creator_cannot_create_episode(self):
        unverified = AdminUser.objects.create_admin(
            email="unverified@studio.com",
            first_name="Unverified",
            password="CreatorPass1!",
            role_type=AdminUser.RoleType.CREATOR,
            username="unverifiedcreator",
            is_verified=False,
        )
        client = admin_auth_client(unverified)
        resp = client.post(
            f"{BASE}/creator/create-episode",
            {
                "season_id": str(self.season.id),
                "title": "Sneaky Ep",
                "description": "Should fail",
                "order": 1,
                "access_type": "free",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class CreatorProfileManagementTests(TestCase):
    """Test suite for creator profile management endpoints."""

    def setUp(self):
        cache.clear()
        self.email_patcher = patch("skiflux.tasks.auth.requests.post")
        mock_post = self.email_patcher.start()
        mock_post.return_value = MagicMock(
            status_code=201, raise_for_status=lambda: None
        )
        self.creator = make_creator(
            email="profile@studio.com",
            username="profilecreator",
            bio="Original bio",
        )
        self.client = admin_auth_client(self.creator)
        self.season = make_season(self.creator, title="Test Season")

    def tearDown(self):
        self.email_patcher.stop()

    # ============ Update Profile Tests ============

    def test_update_profile_with_username_success(self):
        """Test updating creator profile with username."""
        resp = self.client.post(
            f"{BASE}/creator/update-profile",
            {
                "username": "newusername",
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.username, "newusername")
        self.assertIn("newusername", resp.data["data"]["username"])

    def test_update_profile_with_bio_success(self):
        """Test updating creator profile with bio."""
        resp = self.client.post(
            f"{BASE}/creator/update-profile",
            {
                "bio": "Updated bio for creator",
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.bio, "Updated bio for creator")
        self.assertIn("Updated bio for creator", resp.data["data"]["bio"])

    def test_update_profile_with_username_and_bio_success(self):
        """Test updating creator profile with both username and bio."""
        resp = self.client.post(
            f"{BASE}/creator/update-profile",
            {
                "username": "combinedupdate",
                "bio": "Combined update bio",
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.username, "combinedupdate")
        self.assertEqual(self.creator.bio, "Combined update bio")

    def test_update_profile_empty_payload_returns_400(self):
        """Test that empty payload is rejected."""
        resp = self.client.post(
            f"{BASE}/creator/update-profile",
            {},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_profile_unauthenticated_returns_403(self):
        """Test that unauthenticated request is rejected."""
        client = APIClient()
        resp = client.post(
            f"{BASE}/creator/update-profile",
            {"username": "sneaky"},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 403)

    def test_update_profile_returns_correct_data_structure(self):
        """Test that update profile returns correct data structure."""
        resp = self.client.post(
            f"{BASE}/creator/update-profile",
            {
                "username": "newprofileuser",
                "bio": "New profile bio",
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("username", data)
        self.assertIn("bio", data)
        self.assertIn("avatar_url", data)
        self.assertEqual(data["username"], "newprofileuser")
        self.assertEqual(data["bio"], "New profile bio")

    # ============ Get Profile (Profile) Tests ============

    def test_get_profile_returns_200(self):
        """Test getting creator profile returns 200."""
        resp = self.client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_get_profile_returns_correct_data_structure(self):
        """Test that get profile returns correct data structure."""
        resp = self.client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]

        # Check basic fields
        self.assertEqual(str(data["id"]), str(self.creator.id))
        self.assertEqual(data["email"], self.creator.email)
        self.assertEqual(data["username"], self.creator.username)
        self.assertEqual(data["first_name"], self.creator.first_name)
        self.assertEqual(data["bio"], self.creator.bio)

        # Check role and verification
        self.assertEqual(data["role_type"], self.creator.role_type)
        self.assertTrue(data["is_verified"])
        self.assertTrue(data["is_active"])

    def test_get_profile_includes_stats(self):
        """Test that get profile includes stats section."""
        resp = self.client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]

        self.assertIn("stats", data)
        stats = data["stats"]

        # Check stats fields
        self.assertIn("seasons_count", stats)
        self.assertIn("episodes_count", stats)
        self.assertIn("submissions_count", stats)
        self.assertIn("subscribers_count", stats)

    def test_get_profile_stats_accuracy_with_content(self):
        """Test that stats are calculated correctly with content."""
        # Create additional content
        make_episode(self.creator, self.season, title="Ep 1", order=1)
        make_episode(self.creator, self.season, title="Ep 2", order=2)
        make_season(self.creator, title="Season 2")

        resp = self.client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 200)
        stats = resp.data["data"]["stats"]

        self.assertEqual(stats["seasons_count"], 2)
        self.assertEqual(stats["episodes_count"], 2)

    def test_get_profile_includes_timestamps(self):
        """Test that get profile includes created_at and updated_at."""
        resp = self.client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]

        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_get_profile_unauthenticated_returns_403(self):
        """Test that unauthenticated request is rejected."""
        client = APIClient()
        resp = client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 403)

    def test_get_profile_unverified_creator_can_view(self):
        """Test that unverified creator CAN view their profile (for onboarding)."""
        unverified = AdminUser.objects.create_admin(
            email="unverified2@studio.com",
            first_name="Unverified",
            password="CreatorPass1!",
            role_type=AdminUser.RoleType.CREATOR,
            username="unverified2",
            is_verified=False,
            avatar_public_id="avatar/test",
            bio="test",
        )
        client = admin_auth_client(unverified)
        resp = client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 200)

    def test_get_profile_creator_without_avatar_can_view(self):
        """Test that creator without avatar_public_id can view their profile."""
        incomplete = AdminUser.objects.create_admin(
            email="incomplete2@studio.com",
            first_name="Incomplete",
            password="CreatorPass1!",
            role_type=AdminUser.RoleType.CREATOR,
            username="incomplete2",
            is_verified=True,
            avatar_public_id=None,  # Missing avatar
            bio="test",
        )
        client = admin_auth_client(incomplete)
        resp = client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp.status_code, 200)

    def test_get_profile_different_creator_sees_own_profile(self):
        """Test that each creator sees only their own profile."""
        other_creator = make_creator(
            email="other@studio.com",
            username="othercreator",
            bio="Other bio",
        )
        other_client = admin_auth_client(other_creator)

        # Original creator gets their profile
        resp1 = self.client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(str(resp1.data["data"]["id"]), str(self.creator.id))

        # Other creator gets their profile
        resp2 = other_client.get(f"{BASE}/creator/profile")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(str(resp2.data["data"]["id"]), str(other_creator.id))

        # Profiles should be different
        self.assertNotEqual(
            resp1.data["data"]["id"],
            resp2.data["data"]["id"],
        )


class SeasonUpdateUnpublishRemoveTests(TestCase):
    """Test season update, unpublish, and remove operations."""

    def setUp(self):
        cache.clear()
        self.creator = make_creator()
        self.other_creator = make_creator(
            email="other@studio.com", username="othercreator"
        )
        self.client = admin_auth_client(self.creator)
        self.other_client = admin_auth_client(self.other_creator)
        self.season = make_season(self.creator, title="Original Title")

    def test_update_season_success(self):
        """Creator can update their own season."""
        resp = self.client.patch(
            f"{BASE}/creator/season/{self.season.id}/update",
            {
                "title": "Updated Title",
                "description": "New description",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.season.refresh_from_db()
        self.assertEqual(self.season.title, "Updated Title")
        self.assertEqual(self.season.description, "New description")

    def test_update_season_partial_fields(self):
        """Creator can update only some fields."""
        original_description = self.season.description
        resp = self.client.patch(
            f"{BASE}/creator/season/{self.season.id}/update",
            {"title": "New Title"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.season.refresh_from_db()
        self.assertEqual(self.season.title, "New Title")
        self.assertEqual(self.season.description, original_description)

    def test_update_season_permission_denied(self):
        """Other creator cannot update season they don't own."""
        resp = self.other_client.patch(
            f"{BASE}/creator/season/{self.season.id}/update",
            {"title": "Hacked Title"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.season.refresh_from_db()
        self.assertEqual(self.season.title, "Original Title")

    def test_update_season_not_found(self):
        """Updating non-existent season returns 400."""
        import uuid

        resp = self.client.patch(
            f"{BASE}/creator/season/{uuid.uuid4()}/update",
            {"title": "Ghost Title"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_season_no_fields_provided(self):
        """Updating with no fields returns 400."""
        resp = self.client.patch(
            f"{BASE}/creator/season/{self.season.id}/update",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_season_auto_publishes_when_episode_goes_live(self):
        """Season is published automatically when it gains a published episode."""
        from skiflux.services.season_publish_service import SeasonPublishService

        episode = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
            title="Live Episode",
        )
        self.assertFalse(self.season.is_published)

        published = SeasonPublishService().maybe_publish_season_for_episode(episode)
        self.assertTrue(published)
        self.season.refresh_from_db()
        self.assertTrue(self.season.is_published)

    def test_season_stays_unpublished_without_published_episodes(self):
        """Draft-only seasons are not auto-published."""
        make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.DRAFT,
            title="Draft Episode",
        )
        self.season.refresh_from_db()
        self.assertFalse(self.season.is_published)

    def test_auto_publish_is_idempotent(self):
        """Second published episode does not re-run publish side effects."""
        from skiflux.services.season_publish_service import SeasonPublishService

        ep1 = make_episode(
            self.creator,
            self.season,
            order=1,
            status=Episode.Status.PUBLISHED,
        )
        SeasonPublishService().maybe_publish_season_for_episode(ep1)
        ep2 = make_episode(
            self.creator,
            self.season,
            order=2,
            status=Episode.Status.PUBLISHED,
        )
        published_again = SeasonPublishService().maybe_publish_season_for_episode(ep2)
        self.assertFalse(published_again)

    def test_unpublish_season_success(self):
        """Creator can unpublish their season."""
        self.season.is_published = True
        self.season.save()

        resp = self.client.post(
            f"{BASE}/creator/season/{self.season.id}/unpublish",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.season.refresh_from_db()
        self.assertFalse(self.season.is_published)

    def test_unpublish_season_already_unpublished(self):
        """Unpublishing already unpublished season returns error."""
        self.season.is_published = False
        self.season.save()

        resp = self.client.post(
            f"{BASE}/creator/season/{self.season.id}/unpublish",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unpublish_season_permission_denied(self):
        """Other creator cannot unpublish season they don't own."""
        self.season.is_published = True
        self.season.save()

        resp = self.other_client.post(
            f"{BASE}/creator/season/{self.season.id}/unpublish",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.season.refresh_from_db()
        self.assertTrue(self.season.is_published)

    def test_remove_season_success(self):
        """Creator can remove their season."""
        season_id = self.season.id
        resp = self.client.delete(
            f"{BASE}/creator/season/{season_id}/remove",
            format="json",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Season.objects.filter(id=season_id).exists())

    def test_remove_season_cascades_delete_episodes(self):
        """Removing season cascades delete to episodes."""
        episode = make_episode(self.creator, self.season)
        season_id = self.season.id
        episode_id = episode.id

        resp = self.client.delete(
            f"{BASE}/creator/season/{season_id}/remove",
            format="json",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Season.objects.filter(id=season_id).exists())
        self.assertFalse(Episode.objects.filter(id=episode_id).exists())

    def test_remove_season_permission_denied(self):
        """Other creator cannot remove season they don't own."""
        season_id = self.season.id
        resp = self.other_client.delete(
            f"{BASE}/creator/season/{season_id}/remove",
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Season.objects.filter(id=season_id).exists())

    def test_remove_season_not_found(self):
        """Removing non-existent season returns 400."""
        import uuid

        resp = self.client.delete(
            f"{BASE}/creator/season/{uuid.uuid4()}/remove",
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class EpisodeUpdateUnpublishRemoveTests(TestCase):
    """Test episode update, unpublish, and remove operations."""

    def setUp(self):
        cache.clear()
        self.creator = make_creator()
        self.other_creator = make_creator(
            email="other@studio.com", username="othercreator"
        )
        self.client = admin_auth_client(self.creator)
        self.other_client = admin_auth_client(self.other_creator)
        self.season = make_season(self.creator)
        self.episode = make_episode(self.creator, self.season, title="Original Title")

    def test_update_episode_success(self):
        """Creator can update their own episode."""
        resp = self.client.patch(
            f"{BASE}/creator/episode/{self.episode.id}/update",
            {
                "title": "Updated Title",
                "description": "New description",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.title, "Updated Title")
        self.assertEqual(self.episode.description, "New description")

    def test_update_episode_partial_fields(self):
        """Creator can update only some fields."""
        original_description = self.episode.description
        resp = self.client.patch(
            f"{BASE}/creator/episode/{self.episode.id}/update",
            {"title": "New Title"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.title, "New Title")
        self.assertEqual(self.episode.description, original_description)

    def test_update_episode_permission_denied(self):
        """Other creator cannot update episode they don't own."""
        resp = self.other_client.patch(
            f"{BASE}/creator/episode/{self.episode.id}/update",
            {"title": "Hacked Title"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.title, "Original Title")

    def test_update_episode_not_found(self):
        """Updating non-existent episode returns 400."""
        import uuid

        resp = self.client.patch(
            f"{BASE}/creator/episode/{uuid.uuid4()}/update",
            {"title": "Ghost Title"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_episode_no_fields_provided(self):
        """Updating with no fields returns 400."""
        resp = self.client.patch(
            f"{BASE}/creator/episode/{self.episode.id}/update",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_update_episode_while_processing_fails(self):
        """Cannot update episode while it's being processed."""
        self.episode.status = Episode.Status.PROCESSING
        self.episode.save()

        resp = self.client.patch(
            f"{BASE}/creator/episode/{self.episode.id}/update",
            {"title": "New Title"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unpublish_episode_success(self):
        """Creator can unpublish their published episode."""
        self.episode.status = Episode.Status.PUBLISHED
        self.episode.save()

        resp = self.client.post(
            f"{BASE}/creator/episode/{self.episode.id}/unpublish",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.status, Episode.Status.DRAFT)

    def test_unpublish_episode_not_published(self):
        """Cannot unpublish non-published episode."""
        self.episode.status = Episode.Status.DRAFT
        self.episode.save()

        resp = self.client.post(
            f"{BASE}/creator/episode/{self.episode.id}/unpublish",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_unpublish_episode_permission_denied(self):
        """Other creator cannot unpublish episode they don't own."""
        self.episode.status = Episode.Status.PUBLISHED
        self.episode.save()

        resp = self.other_client.post(
            f"{BASE}/creator/episode/{self.episode.id}/unpublish",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.status, Episode.Status.PUBLISHED)

    def test_remove_episode_success(self):
        """Creator can remove their episode."""
        episode_id = self.episode.id
        resp = self.client.delete(
            f"{BASE}/creator/episode/{episode_id}/remove",
            format="json",
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Episode.objects.filter(id=episode_id).exists())

    def test_remove_episode_permission_denied(self):
        """Other creator cannot remove episode they don't own."""
        episode_id = self.episode.id
        resp = self.other_client.delete(
            f"{BASE}/creator/episode/{episode_id}/remove",
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Episode.objects.filter(id=episode_id).exists())

    def test_remove_episode_not_found(self):
        """Removing non-existent episode returns 400."""
        import uuid

        resp = self.client.delete(
            f"{BASE}/creator/episode/{uuid.uuid4()}/remove",
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
