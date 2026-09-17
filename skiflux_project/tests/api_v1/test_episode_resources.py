from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status

from skiflux.models.content import EpisodeResource

from .conftest import (
    make_creator,
    make_season,
    make_episode,
    make_verified_user,
    admin_auth_client,
    user_auth_client,
)

BASE = "/api/v1"


class EpisodeResourceStudioAPITest(TestCase):
    def setUp(self):
        self.creator = make_creator()
        self.other_user = make_creator(email="other@creator.com", username="other")
        self.user = make_verified_user()

        self.season = make_season(self.creator)
        self.episode = make_episode(self.creator, self.season)

        self.client = admin_auth_client(self.creator)
        self.other_client = admin_auth_client(self.other_user)
        self.user_client = user_auth_client(self.user)

    # ─────────────────────────────────────────
    # LIST (STUDIO)
    # ─────────────────────────────────────────
    def test_creator_can_list_resources(self):
        url = f"{BASE}/episodes/{self.episode.id}/resources/"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_non_owner_cannot_access_studio_list(self):
        url = f"{BASE}/episodes/{self.episode.id}/resources/"
        res = self.other_client.get(url)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # ─────────────────────────────────────────
    # ADD FILES
    # ─────────────────────────────────────────
    @patch("skiflux.services.episode_resource_service.upload_to_minio")
    @patch(
        "skiflux.services.episode_resource_service.upload_media_from_minio_task.delay"
    )
    def test_add_file_resources(self, mock_task, mock_upload):
        mock_upload.return_value = "fake-minio-key"

        file = SimpleUploadedFile(
            "test.pdf",
            b"dummy content",
            content_type="application/pdf",
        )

        url = f"{BASE}/episodes/{self.episode.id}/resources/files/"

        res = self.client.post(url, {"files": file}, format="multipart")

        self.assertIn(res.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(EpisodeResource.objects.filter(episode=self.episode).exists())

    def test_add_file_without_files_fails(self):
        url = f"{BASE}/episodes/{self.episode.id}/resources/files/"
        res = self.client.post(url, {}, format="multipart")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # ─────────────────────────────────────────
    # ADD LINKS
    # ─────────────────────────────────────────
    def test_add_link_resources(self):
        url = f"{BASE}/episodes/{self.episode.id}/resources/links/"

        payload = {
            "links": [
                {"label": "Google", "url": "https://google.com"},
                {"label": "Docs", "url": "https://docs.google.com"},
            ]
        }

        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            EpisodeResource.objects.filter(
                episode=self.episode,
                resource_type=EpisodeResource.ResourceType.LINK,
            ).count(),
            2,
        )

    def test_add_invalid_link_fails(self):
        url = f"{BASE}/episodes/{self.episode.id}/resources/links/"

        payload = {"links": [{"label": "", "url": "invalid-url"}]}

        res = self.client.post(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # ─────────────────────────────────────────
    # UPDATE LINK
    # ─────────────────────────────────────────
    def test_update_link_resource(self):
        resource = EpisodeResource.objects.create(
            episode=self.episode,
            resource_type=EpisodeResource.ResourceType.LINK,
            link_label="Old",
            link_url="https://old.com",
            order=0,
        )

        url = f"{BASE}/episodes/{self.episode.id}/resources/{resource.id}/link/"

        payload = {
            "label": "New Label",
            "url": "https://new.com",
        }

        res = self.client.patch(url, payload, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)

        resource.refresh_from_db()
        self.assertEqual(resource.link_label, "New Label")
        self.assertEqual(resource.link_url, "https://new.com")

    # ─────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────
    @patch("skiflux.tasks.content.cleanup_cloudinary_asset_task.delay")
    def test_delete_resource(self, mock_cleanup):
        resource = EpisodeResource.objects.create(
            episode=self.episode,
            resource_type=EpisodeResource.ResourceType.LINK,
            link_label="Delete Me",
            link_url="https://delete.com",
            order=0,
            file_public_id="cloudinary_123",
        )

        url = f"{BASE}/episodes/{self.episode.id}/resources/{resource.id}/"

        res = self.client.delete(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(EpisodeResource.objects.filter(id=resource.id).exists())

    # ─────────────────────────────────────────
    # OWNERSHIP SAFETY
    # ─────────────────────────────────────────
    def test_non_owner_cannot_modify_episode(self):
        url = f"{BASE}/episodes/{self.episode.id}/resources/"

        res = self.other_client.get(url)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
