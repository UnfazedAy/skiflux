from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from unittest.mock import patch

from skiflux.models.content import Episode, EpisodeTask, TaskSubmission
from skiflux.utils.media import derive_submission_proof_type

from .conftest import (
    admin_auth_client,
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
    user_auth_client,
)

BASE = "/api/v1"


class DeriveSubmissionProofTypeTests(TestCase):
    def test_link_submission(self):
        sub = TaskSubmission(submission_url="https://example.com/work")
        self.assertEqual(derive_submission_proof_type(sub), "link")

    def test_image_file_submission(self):
        sub = TaskSubmission(submission_file_content_type="image/jpeg")
        self.assertEqual(derive_submission_proof_type(sub), "image")

    def test_pdf_file_submission(self):
        sub = TaskSubmission(submission_file_content_type="application/pdf")
        self.assertEqual(derive_submission_proof_type(sub), "file")

    def test_document_file_submission(self):
        sub = TaskSubmission(
            submission_file_content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        )
        self.assertEqual(derive_submission_proof_type(sub), "file")

    def test_video_file_submission(self):
        sub = TaskSubmission(submission_file_content_type="video/mp4")
        self.assertEqual(derive_submission_proof_type(sub), "video")


class SubmitTaskWithFileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="submitfile@example.com")
        self.client = user_auth_client(self.user)
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
        )
        self.project_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Upload your design",
            accepted_proof_types=["image", "link"],
        )

    @patch("skiflux.tasks.content.upload_media_from_minio_task.delay")
    @patch("skiflux.utils.media.upload_to_minio")
    def test_submit_project_task_with_file(self, mock_minio, mock_task_delay):
        mock_minio.return_value = "skiflux_task_submissions/temp.jpg"
        image = SimpleUploadedFile(
            "proof.jpg", b"fake-image-bytes", content_type="image/jpeg"
        )

        resp = self.client.post(
            f"{BASE}/episodes/task/submit",
            {
                "episode_id": str(self.episode.id),
                "submission_text": "My design proof",
                "submission_file": image,
            },
            format="multipart",
        )

        self.assertEqual(resp.status_code, 201)
        submission = TaskSubmission.objects.get(task=self.project_task, user=self.user)
        self.assertEqual(submission.submission_text, "My design proof")
        self.assertIsNone(submission.submission_url)
        self.assertEqual(submission.submission_file_name, "proof.jpg")
        self.assertEqual(submission.submission_file_content_type, "image/jpeg")
        mock_minio.assert_called_once()
        mock_task_delay.assert_called_once()

    def test_submit_file_rejected_when_proof_type_not_accepted(self):
        self.project_task.accepted_proof_types = ["link"]
        self.project_task.save(update_fields=["accepted_proof_types"])

        image = SimpleUploadedFile(
            "proof.jpg", b"fake-image-bytes", content_type="image/jpeg"
        )
        resp = self.client.post(
            f"{BASE}/episodes/task/submit",
            {
                "episode_id": str(self.episode.id),
                "submission_file": image,
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_submit_link_still_works(self):
        resp = self.client.post(
            f"{BASE}/episodes/task/submit",
            {
                "episode_id": str(self.episode.id),
                "project_submission": {
                    "submission_url": "https://figma.com/file/abc",
                    "submission_text": "Figma link",
                },
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        submission = TaskSubmission.objects.get(task=self.project_task, user=self.user)
        self.assertEqual(submission.submission_url, "https://figma.com/file/abc")


class SubmissionProofTypeResponseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.creator = make_creator(email="creator@test.com", username="creator1")
        self.season = make_season(self.creator)
        self.episode = make_episode(
            self.creator,
            self.season,
            status=Episode.Status.PUBLISHED,
        )
        self.project_task = EpisodeTask.objects.create(
            episode=self.episode,
            kind=EpisodeTask.Kind.PROJECT_BASED,
            task_brief="Build a website",
        )
        self.user = make_verified_user(email="user1@test.com")

    def test_get_task_submissions_includes_proof_type_for_link(self):
        TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user,
            submission_url="https://example.com/1",
            status=TaskSubmission.Status.PENDING,
        )

        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/",
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["data"]["results"][0]
        self.assertEqual(result["proof_type"], "link")
        self.assertIsNone(result["submission_file_url"])

    def test_get_task_submissions_includes_proof_type_for_image_file(self):
        TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user,
            submission_file_content_type="image/png",
            submission_file_public_id="skiflux_task_submissions/proof123",
            status=TaskSubmission.Status.PENDING,
        )

        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/creator/episode/{self.episode.id}/tasks/"
            f"{self.project_task.id}/submissions/",
            format="json",
        )
        result = response.json()["data"]["results"][0]
        self.assertEqual(result["proof_type"], "image")

    def test_pending_task_submissions_include_proof_type(self):
        TaskSubmission.objects.create(
            task=self.project_task,
            user=self.user,
            submission_file_content_type="video/mp4",
            submission_file_public_id="skiflux_task_submissions/video123",
            status=TaskSubmission.Status.PENDING,
        )

        client = admin_auth_client(self.creator)
        response = client.get(
            f"{BASE}/admin/studio/creators/{self.creator.id}/pending-task-submissions/",
            format="json",
        )
        result = response.json()["data"]["results"][0]
        self.assertEqual(result["proof_type"], "video")
