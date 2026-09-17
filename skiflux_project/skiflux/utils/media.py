import html
import logging
import mimetypes
import textwrap
import time
import uuid
import cloudinary.uploader
import cloudinary.utils

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.cache import cache
from rest_framework import serializers

from skiflux.tasks.auth import send_app_email_task

logger = logging.getLogger(__name__)

UPLOAD_EMAIL_CACHE_TTL = 86400
UPLOAD_ATTEMPT_CACHE_TTL = 86400 * 30


def get_s3_client():
    """Initializes the boto3 client for cloudfare R2."""
    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT_URL,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
        ),
    )


def _get_bucket_name():
    return getattr(settings, "MINIO_BUCKET_NAME", "video-uploads")


def _ensure_https(url: str | None) -> str | None:
    if url and url.startswith("http://"):
        return "https://" + url[7:]
    return url


def upload_to_minio(file, folder="temp_uploads") -> str:
    s3_client = get_s3_client()
    bucket_name = _get_bucket_name()

    ext = file.name.split(".")[-1] if "." in file.name else "bin"
    unique_filename = f"{folder}/{uuid.uuid4().hex}.{ext}"
    content_type = getattr(
        file,
        "content_type",
        mimetypes.guess_type(file.name)[0] or "application/octet-stream",
    )

    s3_client.upload_fileobj(
        file, bucket_name, unique_filename, ExtraArgs={"ContentType": content_type}
    )
    return unique_filename


def get_minio_presigned_url(object_key: str, expires_in=3600) -> str:
    s3_client = get_s3_client()
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _get_bucket_name(), "Key": object_key},
        ExpiresIn=expires_in,
    )


def delete_from_minio(object_key: str):
    s3_client = get_s3_client()
    s3_client.delete_object(Bucket=_get_bucket_name(), Key=object_key)


def upload_to_cloudinary(
    file_or_url, folder="skiflux_uploads", is_private=True, resource_type="auto"
):

    upload_type = "private" if is_private else "upload"

    upload_result = cloudinary.uploader.upload(
        file_or_url, folder=folder, type=upload_type, resource_type=resource_type
    )
    return upload_result.get("public_id")


def cloudinary_resource_type_for_submission_file(content_type: str | None) -> str:
    ct = (content_type or "").lower()
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("image/"):
        return "image"
    return "raw"


def derive_submission_proof_type(submission) -> str | None:
    """Derive proof type from stored submission fields."""
    from skiflux.models.content import EpisodeTask

    if submission.submission_file_public_id or submission.submission_file_content_type:
        ct = (submission.submission_file_content_type or "").lower()
        if ct.startswith("video/"):
            return EpisodeTask.ProofType.VIDEO
        if ct.startswith("image/"):
            return EpisodeTask.ProofType.IMAGE
        return EpisodeTask.ProofType.FILE
    if submission.submission_url:
        return EpisodeTask.ProofType.LINK
    return None


def get_submission_file_url(submission) -> str | None:
    if submission.submission_file_url:
        return _ensure_https(submission.submission_file_url)
    if not submission.submission_file_public_id:
        return None
    resource_type = cloudinary_resource_type_for_submission_file(
        submission.submission_file_content_type
    )
    return get_private_media_url(
        submission.submission_file_public_id,
        resource_type=resource_type,
    )


def proof_type_allowed(derived: str, accepted: list) -> bool:
    if not accepted:
        return True
    normalized = {str(item).lower() for item in accepted}
    if derived in normalized:
        return True
    link_aliases = {"figma", "github", "other", "link"}
    if derived == "link" and normalized & link_aliases:
        return True
    return False


def get_private_media_url(public_id: str, resource_type="image") -> str:
    if not public_id:
        return None

    if public_id.startswith("http"):
        return _ensure_https(public_id)

    signed_url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        type="private",
        sign_url=True,
        resource_type=resource_type,
        secure=True,
    )
    return signed_url


def get_private_video_download_url(public_id: str, expires_in=3600) -> str | None:
    """
    Returns a signed MP4 download/playback URL.
    Use this for direct video playback on mobile — not HLS.
    """
    if not public_id:
        return None
    if public_id.startswith("http"):
        return _ensure_https(public_id)

    signed_url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        type="private",
        sign_url=True,
        resource_type="video",
        format="mp4",
        expires_at=int(time.time()) + expires_in,
        secure=True,
    )
    return signed_url


def get_private_video_url(public_id: str, expires_in=3600) -> str:
    if not public_id:
        return None
    if public_id.startswith("http"):
        return _ensure_https(public_id)

    signed_url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        type="private",
        sign_url=True,
        resource_type="video",
        expires_at=int(time.time()) + expires_in,
        secure=True,
    )
    return signed_url


def get_private_video_thumbnail_url(public_id: str) -> str:
    if not public_id:
        return None
    if public_id.startswith("http"):
        return public_id

    signed_url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        type="private",
        sign_url=True,
        resource_type="video",
        format="jpg",
    )
    return signed_url


def delete_from_cloudinary(
    public_id: str,
    resource_type: str = "image",
    is_private: bool = True,
) -> dict:
    """
    Delete a Cloudinary resource.

    Args:
        public_id: Cloudinary public ID
        resource_type: image, video, raw
        is_private: Whether the asset was uploaded as private

    Returns:
        Cloudinary destroy response
    """
    if not public_id:
        return {"result": "not_found"}

    upload_type = "private" if is_private else "upload"

    return cloudinary.uploader.destroy(
        public_id,
        resource_type=resource_type,
        type=upload_type,
        invalidate=True,
    )


def get_hls_streaming_url(
    public_id: str,
    expires_in: int = 3600,
    duration_seconds: int = None,
) -> str | None:
    if not public_id:
        return None
    if public_id.startswith("http"):
        return _ensure_https(public_id)

    options = {
        "resource_type": "video",
        "type": "private",
        "sign_url": True,
        "secure": True,
        "expires_at": int(time.time()) + expires_in,
        "streaming_profile": "auto",
        "format": "m3u8",
    }
    if duration_seconds:
        # options["duration"] = duration_seconds
        options["start_offset"] = 0
        options["end_offset"] = duration_seconds

    signed_url, _ = cloudinary.utils.cloudinary_url(public_id, **options)
    return signed_url


def _upload_attempt_cache_key(episode_id: str) -> str:
    return f"upload_attempt:{episode_id}"


def bump_upload_attempt(episode_id: str) -> int:
    """Increment per-episode upload attempt (new video queued).
    Resets email dedup scope."""
    key = _upload_attempt_cache_key(episode_id)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=UPLOAD_ATTEMPT_CACHE_TTL)
        return 1


def get_upload_attempt(episode_id: str) -> int:
    return cache.get(_upload_attempt_cache_key(episode_id)) or 1


def _upload_email_cache_key(
    episode_id, outcome: str, attempt: int | None = None
) -> str:
    if attempt is None:
        attempt = get_upload_attempt(episode_id)
    return f"upload_email_sent:{episode_id}:{attempt}:{outcome}"


def creator_display_name(admin) -> str:
    if admin.display_name:
        return admin.display_name
    name = f"{admin.first_name} {admin.last_name}".strip()
    return name or admin.email


def plain_text_safe(value: str) -> str:
    """Escape user-controlled values in plain-text email bodies."""
    return html.escape(str(value), quote=False)


def _try_send_upload_email(episode_id, outcome: str, send_fn, *args, **kwargs) -> bool:
    key = _upload_email_cache_key(episode_id, outcome)
    if cache.get(key) == "1":
        return False
    if not cache.add(key, "pending", timeout=300):
        return False
    try:
        send_fn(*args, **kwargs)
    except Exception:
        cache.delete(key)
        logger.exception(
            "Failed to enqueue upload notification email",
            extra={"episode_id": episode_id, "outcome": outcome},
        )
        raise
    cache.set(key, "1", timeout=UPLOAD_EMAIL_CACHE_TTL)
    return True


def _enqueue_content_email(subject, message, email, html_message=None):
    task_kwargs = {
        "args": [subject, message, email],
    }
    if html_message:
        task_kwargs["kwargs"] = {"html_message": html_message}
    send_app_email_task.apply_async(**task_kwargs)


def _send_upload_notification(
    episode_id,
    outcome,
    subject,
    message,
    email,
    html_message,
) -> bool:
    def _send():
        _enqueue_content_email(subject, message, email, html_message)

    if episode_id is not None:
        return _try_send_upload_email(episode_id, outcome, _send)
    _send()
    return True


def send_content_upload_received_email(
    email,
    episode_name,
    creator_name,
    episode_id=None,
    html_message=None,
) -> bool:
    subject = "Content Upload Received"
    safe_name = plain_text_safe(creator_name)
    safe_title = plain_text_safe(episode_name)
    message = textwrap.dedent(f"""\
        Hello {safe_name},

        Thank you for uploading your content.
        We have received your video and are preparing it for playback.
        You will receive another email once it is live on the platform.

        Content Title: {safe_title}

        Best,
        The SkiFlux Team
        """)
    if html_message is None:
        safe_name = html.escape(creator_name)
        safe_title = html.escape(episode_name)
        html_message = (
            f"<p>Hello {safe_name},</p>"
            "<p>Thank you for uploading your content. "
            "We have received your video and are preparing it for playback. "
            "You will receive another email once it is live on the platform.</p>"
            f"<p><strong>Content Title:</strong> {safe_title}</p>"
            "<p>Best,<br>The SkiFlux Team</p>"
        )

    return _send_upload_notification(
        episode_id, "received", subject, message, email, html_message
    )


def send_content_under_review_email(
    email,
    episode_name,
    creator_name,
    episode_id=None,
    html_message=None,
) -> bool:
    subject = "Your Content Is Under Review"
    safe_name = plain_text_safe(creator_name)
    safe_title = plain_text_safe(episode_name)
    message = textwrap.dedent(f"""\
        Hello {safe_name},

        Your video has been received and is now under review by our team.
        We will notify you once a decision has been made.

        Content Title: {safe_title}

        Best,
        The SkiFlux Team
        """)
    if html_message is None:
        safe_name = html.escape(creator_name)
        safe_title = html.escape(episode_name)
        html_message = (
            f"<p>Hello {safe_name},</p>"
            "<p>Your video has been received and is now under review by our team. "
            "We will notify you once a decision has been made.</p>"
            f"<p><strong>Content Title:</strong> {safe_title}</p>"
            "<p>Best,<br>The SkiFlux Team</p>"
        )
    return _send_upload_notification(
        episode_id, "under_review", subject, message, email, html_message
    )


def send_content_approved_email(
    email,
    episode_name,
    creator_name,
    episode_id=None,
    html_message=None,
) -> bool:
    """Sent when an admin approves an episode that was in REVIEW."""
    subject = "Your Content Has Been Approved"
    safe_name = plain_text_safe(creator_name)
    safe_title = plain_text_safe(episode_name)
    message = textwrap.dedent(f"""\
        Hello {safe_name},

        Great news! Your content has been reviewed and approved.
        It is now live on the platform.

        Content Title: {safe_title}

        Best,
        The SkiFlux Team
        """)
    if html_message is None:
        safe_name = html.escape(creator_name)
        safe_title = html.escape(episode_name)
        html_message = (
            f"<p>Hello {safe_name},</p>"
            "<p>Great news! Your content has been reviewed and approved. "
            "It is now live on the platform.</p>"
            f"<p><strong>Content Title:</strong> {safe_title}</p>"
            "<p>Best,<br>The SkiFlux Team</p>"
        )
    return _send_upload_notification(
        episode_id, "approved", subject, message, email, html_message
    )


def send_content_published_email(
    email,
    episode_name,
    creator_name,
    episode_id=None,
    html_message=None,
) -> bool:
    subject = "Your Content Is Now Live"
    safe_name = plain_text_safe(creator_name)
    safe_title = plain_text_safe(episode_name)
    message = textwrap.dedent(f"""\
        Hello {safe_name},

        Great news! Your content has finished processing and
        is now available on the platform.

        Content Title: {safe_title}

        Best,
        The SkiFlux Team
        """)
    if html_message is None:
        safe_name = html.escape(creator_name)
        safe_title = html.escape(episode_name)
        html_message = (
            f"<p>Hello {safe_name},</p>"
            "<p>Great news! Your content has finished processing and "
            "is now available on the platform.</p>"
            f"<p><strong>Content Title:</strong> {safe_title}</p>"
            "<p>Best,<br>The SkiFlux Team</p>"
        )

    return _send_upload_notification(
        episode_id, "published", subject, message, email, html_message
    )


def send_content_success_email(
    email,
    episode_name,
    creator_name,
    episode_id=None,
    html_message=None,
) -> bool:
    """Backward-compatible alias for the post-processing 'now live' email."""
    return send_content_published_email(
        email, episode_name, creator_name, episode_id, html_message
    )


def send_content_rejected_email(
    email,
    rejection_reason,
    episode_name,
    creator_name,
    episode_id=None,
    html_message=None,
) -> bool:
    subject = "Content Rejected"
    safe_name = plain_text_safe(creator_name)
    safe_title = plain_text_safe(episode_name)
    safe_reason = plain_text_safe(rejection_reason)
    message = textwrap.dedent(f"""\
        Hello {safe_name},

        Thank you for uploading your content.
        Unfortunately, it could not be processed
        due to the following reason:

        Content Title: {safe_title}
        Reason: {safe_reason}

        Best,
        The SkiFlux Team
        """)
    if html_message is None:
        safe_name = html.escape(creator_name)
        safe_title = html.escape(episode_name)
        safe_reason = html.escape(rejection_reason)
        html_message = (
            f"<p>Hello {safe_name},</p>"
            "<p>Thank you for uploading your content. "
            "Unfortunately, it could not be processed "
            "due to the following reason:</p>"
            f"<p><strong>Content Title:</strong> {safe_title}</p>"
            f"<p><strong>Reason:</strong> {safe_reason}</p>"
            "<p>Best,<br>The SkiFlux Team</p>"
        )

    return _send_upload_notification(
        episode_id, "rejected", subject, message, email, html_message
    )


def send_content_failed_email(
    email,
    failure_reason,
    episode_name,
    creator_name,
    episode_id=None,
    html_message=None,
) -> bool:
    subject = "Content Upload Failed"
    safe_name = plain_text_safe(creator_name)
    safe_title = plain_text_safe(episode_name)
    safe_reason = plain_text_safe(failure_reason)
    message = textwrap.dedent(f"""\
        Hello {safe_name},

        Your video upload could not be completed.

        Content Title: {safe_title}
        Reason: {safe_reason}

        Please try uploading again. If the problem persists, contact support.

        Best,
        The SkiFlux Team
        """)
    if html_message is None:
        safe_name = html.escape(creator_name)
        safe_title = html.escape(episode_name)
        safe_reason = html.escape(failure_reason)
        html_message = (
            f"<p>Hello {safe_name},</p>"
            "<p>Your video upload could not be completed.</p>"
            f"<p><strong>Content Title:</strong> {safe_title}</p>"
            f"<p><strong>Reason:</strong> {safe_reason}</p>"
            "<p>Please try uploading again. "
            "If the problem persists, contact support.</p>"
            "<p>Best,<br>The SkiFlux Team</p>"
        )

    return _send_upload_notification(
        episode_id, "failed", subject, message, email, html_message
    )


def validate_uploaded_video(value, max_size_mb: int, allowed_types: list[str]):
    """Shared validator for uploaded video files."""
    if value.size > max_size_mb * 1024 * 1024:
        raise serializers.ValidationError(
            f"Video file size cannot exceed {max_size_mb}MB."
        )
    if value.content_type not in allowed_types:
        raise serializers.ValidationError(
            f"Unsupported video format. Allowed: {', '.join(allowed_types)}"
        )
    return value


def validate_uploaded_thumbnail(value, max_size_mb: int, allowed_types: list[str]):
    """Shared validator for uploaded thumbnail files."""
    if not value:
        return value
    if value.size > max_size_mb * 1024 * 1024:
        raise serializers.ValidationError(
            f"Thumbnail size cannot exceed {max_size_mb}MB."
        )
    if value.content_type not in allowed_types:
        raise serializers.ValidationError(
            "Unsupported thumbnail format. Upload a JPEG, PNG, or WEBP image."
        )
    return value
