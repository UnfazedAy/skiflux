import tempfile
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings

from skiflux.models.content import Episode
from skiflux.services.episode_upload_service import publish_episode_when_streaming_ready
from skiflux.tasks.content import upload_media_from_path_task
from skiflux.utils.media import (
    _upload_email_cache_key,
    bump_upload_attempt,
    get_upload_attempt,
    send_content_rejected_email,
    send_content_upload_received_email,
)
from tests.api_v1.conftest import make_creator, make_episode, make_season

STREAMING_READY_EAGER = [
    {
        "status": "complete",
        "format": "m3u8",
        "secure_url": "https://cdn.example/vid.m3u8",
    }
]


@pytest.fixture
def episode_processing(db):
    creator = make_creator(email="upload@studio.com", username="uploadcreator")
    season = make_season(creator)
    return make_episode(
        creator,
        season,
        title="Upload Test",
        order=1,
        status=Episode.Status.PROCESSING,
    )


def _run_upload_task(episode, resource_type="video", retries=0):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.write(b"fake-video")
    tmp.close()
    upload_media_from_path_task.push_request(retries=retries)
    try:
        return upload_media_from_path_task.run(
            str(episode.id),
            tmp.name,
            "skiflux",
            "Episode",
            "video_public_id" if resource_type == "video" else "thumbnail_public_id",
            resource_type,
        )
    finally:
        upload_media_from_path_task.pop_request()


def _simulate_eager_webhook(episode, public_id):
    publish_episode_when_streaming_ready(
        str(episode.id),
        public_id,
        STREAMING_READY_EAGER,
    )


def _email_task_args(mock_email, index=0):
    call = mock_email.call_args_list[index]
    if call.kwargs.get("args"):
        return call.kwargs["args"]
    return call.args[0]


def _email_subject(mock_email, index=0):
    return _email_task_args(mock_email, index)[0]


def _email_recipient(mock_email, index=0):
    return _email_task_args(mock_email, index)[2]


@pytest.mark.django_db
@override_settings(CLOUDINARY_EAGER_WEBHOOK_URL="")
@patch("skiflux.tasks.content.finalize_episode_streaming_fallback_task.apply_async")
@patch("skiflux.tasks.content.cloudinary.uploader.destroy")
@patch("skiflux.utils.media.send_app_email_task.apply_async")
@patch(
    "skiflux.tasks.content.cloudinary.uploader.upload",
    return_value={"public_id": "vid123", "duration": 60},
)
def test_video_success_publishes_via_eager_and_emails(
    mock_upload, mock_email, mock_destroy, mock_fallback, episode_processing
):
    cache.clear()
    bump_upload_attempt(str(episode_processing.id))
    _run_upload_task(episode_processing, resource_type="video")
    episode_processing.refresh_from_db()
    assert episode_processing.status == Episode.Status.PROCESSING
    assert episode_processing.video_public_id == "vid123"
    assert mock_email.call_count == 1
    assert _email_subject(mock_email) == "Content Upload Received"
    mock_fallback.assert_not_called()

    _simulate_eager_webhook(episode_processing, "vid123")
    episode_processing.refresh_from_db()
    assert episode_processing.status == Episode.Status.PUBLISHED
    assert mock_email.call_count == 2
    assert _email_subject(mock_email, 1) == "Your Content Is Now Live"
    assert _email_recipient(mock_email, 0) == "upload@studio.com"
    attempt = get_upload_attempt(str(episode_processing.id))
    key = _upload_email_cache_key(str(episode_processing.id), "received", attempt)
    assert cache.get(key) == "1"


@pytest.mark.django_db
@patch("skiflux.utils.media.send_app_email_task.apply_async")
@patch(
    "skiflux.tasks.content.cloudinary.uploader.upload",
    side_effect=RuntimeError("upload failed"),
)
def test_video_exhausted_retries_failed(mock_upload, mock_email, episode_processing):
    cache.clear()
    bump_upload_attempt(str(episode_processing.id))
    with pytest.raises(RuntimeError):
        _run_upload_task(episode_processing, resource_type="video", retries=5)
    episode_processing.refresh_from_db()
    assert episode_processing.status == Episode.Status.FAILED
    assert mock_email.call_count == 1
    assert _email_subject(mock_email) == "Content Upload Failed"


@pytest.mark.django_db
@patch("skiflux.utils.media.send_app_email_task.apply_async")
@patch(
    "skiflux.tasks.content.cloudinary.uploader.upload",
    return_value={"public_id": "thumb123"},
)
def test_thumbnail_does_not_email(mock_upload, mock_email, episode_processing):
    cache.clear()
    _run_upload_task(episode_processing, resource_type="image")
    mock_email.assert_not_called()


@pytest.mark.django_db
@patch("skiflux.utils.media.send_app_email_task.apply_async")
def test_email_idempotent_on_retry(mock_email, episode_processing):
    cache.clear()
    bump_upload_attempt(str(episode_processing.id))
    send_content_upload_received_email(
        email="upload@studio.com",
        episode_name="Upload Test",
        creator_name="Creator",
        episode_id=str(episode_processing.id),
    )
    send_content_upload_received_email(
        email="upload@studio.com",
        episode_name="Upload Test",
        creator_name="Creator",
        episode_id=str(episode_processing.id),
    )
    assert mock_email.call_count == 1


@pytest.mark.django_db
@patch("skiflux.utils.media.send_app_email_task.apply_async")
def test_rejection_email_sent_again_after_new_upload_attempt(
    mock_email,
    episode_processing,
):
    cache.clear()
    episode_id = str(episode_processing.id)
    bump_upload_attempt(episode_id)
    send_content_rejected_email(
        email="upload@studio.com",
        rejection_reason="Too long",
        episode_name="Upload Test",
        creator_name="Creator",
        episode_id=episode_id,
    )
    bump_upload_attempt(episode_id)
    send_content_rejected_email(
        email="upload@studio.com",
        rejection_reason="Invalid file",
        episode_name="Upload Test",
        creator_name="Creator",
        episode_id=episode_id,
    )
    assert mock_email.call_count == 2


@pytest.mark.django_db
@patch("skiflux.utils.media.send_app_email_task.apply_async")
def test_webhook_publish_skipped_without_hls(mock_email, episode_processing):
    cache.clear()
    bump_upload_attempt(str(episode_processing.id))
    episode_processing.video_public_id = "vid-pending"
    episode_processing.save(update_fields=["video_public_id"])
    published = publish_episode_when_streaming_ready(
        str(episode_processing.id),
        "vid-pending",
        [{"format": "jpg", "secure_url": "https://cdn.example/x.jpg"}],
    )
    episode_processing.refresh_from_db()
    assert published is False
    assert episode_processing.status == Episode.Status.PROCESSING
    mock_email.assert_not_called()
