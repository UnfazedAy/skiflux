from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from skiflux.models.content import EpisodeComment

from .conftest import (
    admin_auth_client,
    make_admin_with_role,
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class AudioCommentsAndSkillworldTests(TestCase):
    def setUp(self):
        # Create user
        self.user = make_verified_user(email="learner@example.com", is_onboarded=False)
        self.client = user_auth_client(self.user)

        # Create creator and content
        self.creator = make_creator()
        self.season = make_season(creator=self.creator)
        self.episode = make_episode(creator=self.creator, season=self.season)

    def test_onboarding_multiple_skillworlds(self):
        payload = {
            "username": "onboarded_learner",
            "skillworld": ["code", "design"],
            "goal": ["learn_skill"],
        }
        resp = self.client.post(
            f"{BASE}/profile/complete-onboarding/", payload, format="multipart"
        )
        self.assertEqual(resp.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_onboarded)
        self.assertEqual(self.user.skillworld, ["code", "design"])

    def test_list_learners_filtering_by_skillworld(self):
        make_verified_user(
            email="writing_user@example.com",
            username="writer_u",
            is_onboarded=True,
            skillworld=["writing"],
        )
        # Onboard self.user with code and design
        self.user.username = "coder_u"
        self.user.skillworld = ["code", "design"]
        self.user.is_onboarded = True
        self.user.save()

        # Admin user with view permission
        from skiflux.models.admin_user import Permission

        admin, _ = make_admin_with_role(
            [Permission.ADMIN_USERS_VIEW], email="viewadmin@skiflux.com"
        )
        admin_client = admin_auth_client(admin)

        # Filter by code
        resp = admin_client.get(f"{BASE}/admin/learners?skillworld=code")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        emails = [r["email"] for r in results]
        self.assertIn("learner@example.com", emails)
        self.assertNotIn("writing_user@example.com", emails)

        # Filter by writing
        resp = admin_client.get(f"{BASE}/admin/learners?skillworld=writing")
        self.assertEqual(resp.status_code, 200)
        results = resp.data["data"]["results"]
        emails = [r["email"] for r in results]
        self.assertIn("writing_user@example.com", emails)
        self.assertNotIn("learner@example.com", emails)

    def test_add_comment_validation_and_audio(self):

        with (
            patch("skiflux.utils.media.upload_to_minio") as mock_minio,
            patch(
                "skiflux.tasks.content.upload_media_from_minio_task.delay"
            ) as mock_task,
            patch("skiflux.services.content_service.moderate_comment_task.delay"),
        ):
            mock_minio.return_value = "skiflux_comments/temp_audio.wav"

            # 1. Error: Neither text nor audio
            resp = self.client.post(
                f"{BASE}/episodes/comment",
                {
                    "episode_id": str(self.episode.id),
                },
            )
            self.assertEqual(resp.status_code, 400)

            # 2. Success: Text only
            resp = self.client.post(
                f"{BASE}/episodes/comment",
                {
                    "episode_id": str(self.episode.id),
                    "text": "Great episode!",
                },
            )
            self.assertEqual(resp.status_code, 201)
            self.assertEqual(
                EpisodeComment.objects.filter(episode=self.episode).count(), 1
            )
            comment = EpisodeComment.objects.first()
            self.assertEqual(comment.text, "Great episode!")
            self.assertIsNone(comment.audio_public_id)

            # 3. Success: Audio only
            audio_file = SimpleUploadedFile(
                "comment.wav", b"dummy audio content", content_type="audio/wav"
            )
            resp = self.client.post(
                f"{BASE}/episodes/comment",
                {
                    "episode_id": str(self.episode.id),
                    "audio_file": audio_file,
                },
                format="multipart",
            )
            self.assertEqual(resp.status_code, 201)

            # Verify minio was called and celery task dispatched
            mock_minio.assert_called_once()
            mock_task.assert_called_once()

            comment_audio = EpisodeComment.objects.order_by("-created_at").first()
            self.assertEqual(comment_audio.text, "")

    def test_celery_task_updates_audio_public_id(self):
        import skiflux.tasks.content  # Load tasks safely after Django initialization

        with (
            patch("skiflux.tasks.content.get_minio_presigned_url") as mock_presigned,
            patch("skiflux.tasks.content.cloudinary.uploader.upload") as mock_upload,
        ):
            mock_presigned.return_value = "https://mock-minio/signed-url"
            mock_upload.return_value = {
                "public_id": "cloudinary_audio_123",
                "duration": 15.0,
            }

            comment = EpisodeComment.objects.create(
                user=self.user, episode=self.episode, text=""
            )

            res = skiflux.tasks.content.upload_media_from_minio_task(
                instance_id=str(comment.id),
                minio_object_key="skiflux_comments/temp.wav",
                field_name="audio_public_id",
                model_name="EpisodeComment",
                resource_type="video",
            )
            self.assertIn("Uploaded EpisodeComment Audio", res)

            comment.refresh_from_db()
            self.assertEqual(comment.audio_public_id, "cloudinary_audio_123")
