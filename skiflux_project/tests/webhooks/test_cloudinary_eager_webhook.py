import json
from unittest.mock import patch

import pytest
from django.test import Client

from skiflux.models.content import Episode
from skiflux.services.episode_upload_service import handle_cloudinary_eager_payload
from tests.api_v1.conftest import make_creator, make_episode, make_season


@pytest.fixture
def episode_processing(db):
    creator = make_creator(email="webhook@studio.com", username="webhookcreator")
    season = make_season(creator)
    return make_episode(
        creator,
        season,
        title="Webhook Test",
        order=1,
        status=Episode.Status.PROCESSING,
    )


WEBHOOK_URL = "/api/v1/webhooks/cloudinary/eager/"


def _email_task_args(mock_email, index=0):
    call = mock_email.call_args_list[index]
    if call.kwargs.get("args"):
        return call.kwargs["args"]
    return call.args[0]


EAGER_PAYLOAD = {
    "notification_type": "eager",
    "public_id": "skiflux_content/vid123",
    "context": {"episode_id": ""},
    "eager": [
        {
            "status": "complete",
            "format": "m3u8",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/v1/vid.m3u8",
        }
    ],
}


@pytest.mark.django_db
@patch("skiflux.views.webhooks.verify_cloudinary_notification", return_value=True)
@patch("skiflux.views.webhooks.process_cloudinary_eager_webhook_task.delay")
def test_webhook_accepts_valid_signature(mock_task, mock_verify, episode_processing):
    payload = {
        **EAGER_PAYLOAD,
        "context": {"episode_id": str(episode_processing.id)},
        "public_id": "vid-webhook",
    }
    episode_processing.video_public_id = "vid-webhook"
    episode_processing.save(update_fields=["video_public_id"])

    client = Client()
    response = client.post(
        WEBHOOK_URL,
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    mock_task.assert_called_once()
    assert mock_task.call_args[0][0]["public_id"] == "vid-webhook"


@pytest.mark.django_db
@patch("skiflux.utils.media.send_app_email_task.apply_async")
def test_handle_eager_payload_publishes_when_hls_ready(mock_email, episode_processing):
    from skiflux.utils.media import bump_upload_attempt

    bump_upload_attempt(str(episode_processing.id))
    episode_processing.video_public_id = "vid-ready"
    episode_processing.save(update_fields=["video_public_id"])

    payload = {
        **EAGER_PAYLOAD,
        "context": {"episode_id": str(episode_processing.id)},
        "public_id": "vid-ready",
    }
    result = handle_cloudinary_eager_payload(payload)
    episode_processing.refresh_from_db()

    assert "published" in result
    assert episode_processing.status == Episode.Status.PUBLISHED
    assert mock_email.call_count == 1
    assert _email_task_args(mock_email)[0] == "Your Content Is Now Live"


@pytest.mark.django_db
def test_webhook_rejects_invalid_signature():
    client = Client()
    response = client.post(
        WEBHOOK_URL,
        data=json.dumps(EAGER_PAYLOAD),
        content_type="application/json",
    )
    assert response.status_code == 401
