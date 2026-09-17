import logging
import re
from typing import Any

from django.core.cache import cache

from skiflux.models.content import Episode
from skiflux.repositories.content_repository import ContentRepository
from skiflux.services.notification_service import NotificationService
from skiflux.utils.media import (
    creator_display_name,
    send_content_failed_email,
    send_content_published_email,
    send_content_under_review_email,
)

logger = logging.getLogger(__name__)

EPISODE_PUBLIC_ID_CACHE_TTL = 86400 * 7
_CONTEXT_EPISODE_ID = re.compile(r"episode_id=([^|]+)")


def register_episode_public_id(episode_id: str, public_id: str) -> None:
    cache.set(
        f"cloudinary_episode:{public_id}",
        str(episode_id),
        timeout=EPISODE_PUBLIC_ID_CACHE_TTL,
    )


def resolve_episode_id(payload: dict[str, Any]) -> str | None:
    context = payload.get("context")
    if isinstance(context, dict):
        episode_id = context.get("episode_id")
        if episode_id:
            return str(episode_id)
    if isinstance(context, str):
        match = _CONTEXT_EPISODE_ID.search(context)
        if match:
            return match.group(1).strip()

    public_id = payload.get("public_id")
    if public_id:
        cached = cache.get(f"cloudinary_episode:{public_id}")
        if cached:
            return str(cached)
    return None


def eager_list_has_hls(eager: list | None) -> bool:
    if not eager:
        return False
    for item in eager:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "failed":
            continue
        fmt = (item.get("format") or "").lower()
        url = item.get("secure_url") or item.get("url") or ""
        if fmt == "m3u8" or ".m3u8" in url:
            return True
    return False


def eager_transformation_failed(eager: list | None) -> tuple[bool, str]:
    if not eager:
        return False, ""
    for item in eager:
        if isinstance(item, dict) and item.get("status") == "failed":
            return True, item.get("reason") or "Streaming preparation failed."
    return False, ""


def publish_episode_when_streaming_ready(
    episode_id: str,
    public_id: str,
    eager: list | None,
) -> bool:
    content_repo = ContentRepository()
    episode = content_repo.get_episode_with_creator(episode_id)
    if not episode:
        logger.warning("Episode %s not found for publish", episode_id)
        return False

    failed, reason = eager_transformation_failed(eager)
    if failed:
        content_repo.update_episode_status(episode_id, Episode.Status.FAILED)
        send_content_failed_email(
            email=episode.creator.email,
            failure_reason=reason,
            episode_name=episode.title,
            creator_name=creator_display_name(episode.creator),
            episode_id=str(episode.id),
        )
        return False

    if not eager_list_has_hls(eager):
        logger.info(
            "Streaming not ready for episode %s (public_id=%s); skipping publish",
            episode_id,
            public_id,
        )
        return False

    updated = content_repo.transition_episode_status(
        episode_id=episode_id,
        public_id=public_id,
        from_status=Episode.Status.PROCESSING,
        to_status=Episode.Status.PUBLISHED,
    )
    if updated:
        send_content_published_email(
            email=episode.creator.email,
            episode_name=episode.title,
            creator_name=creator_display_name(episode.creator),
            episode_id=str(episode.id),
        )

        try:
            repo = ContentRepository()
            notif = NotificationService()

            followers = repo.get_followers_with_notifications(episode.creator)
            payload = {
                "episode_id": str(episode.id),
                "episode_title": episode.title,
                "creator_id": str(episode.creator.id),
                "creator_name": creator_display_name(episode.creator),
            }
            title = f"New episode from {creator_display_name(episode.creator)}"
            body = f"'{episode.title}' is now available."

            for follower in followers:
                try:
                    notif.create_notification(
                        user=follower,
                        type="followed_creator_new_episode",
                        title=title,
                        body=body,
                        data=payload,
                    )
                    notif.send_push_for_event(
                        user=follower,
                        event_type="followed_creator_new_episode",
                        title=title,
                        body=body,
                        data=payload,
                    )
                except Exception:
                    logger.warning(
                        "Failed follower new episode notif for %s", follower.id
                    )
        except Exception:
            logger.warning("Failed to notify followers of new episode %s", episode_id)

        episode = content_repo.get_episode(episode_id)
        if episode:
            from skiflux.services.season_publish_service import SeasonPublishService

            SeasonPublishService().maybe_publish_season_for_episode(episode)

        return True

    if episode.status == Episode.Status.PUBLISHED:
        return True
    logger.warning(
        "Could not publish episode %s for public_id %s (status=%s)",
        episode_id,
        public_id,
        episode.status,
    )
    return False


def set_episode_under_review(
    episode_id: str,
    public_id: str,
    eager: list | None,
) -> bool:
    content_repo = ContentRepository()
    episode = content_repo.get_episode_with_creator(episode_id)
    if not episode:
        logger.warning("Episode %s not found for review transition", episode_id)
        return False

    failed, reason = eager_transformation_failed(eager)
    if failed:
        content_repo.update_episode_status(episode_id, Episode.Status.FAILED)
        send_content_failed_email(
            email=episode.creator.email,
            failure_reason=reason,
            episode_name=episode.title,
            creator_name=creator_display_name(episode.creator),
            episode_id=str(episode.id),
        )
        return False

    if not eager_list_has_hls(eager):
        logger.info(
            "Streaming not ready for episode %s (public_id=%s); skipping review transition",  # noqa: E501
            episode_id,
            public_id,
        )
        return False

    updated = content_repo.transition_episode_status(
        episode_id=episode_id,
        public_id=public_id,
        from_status=Episode.Status.PROCESSING,
        to_status=Episode.Status.REVIEW,
    )

    if updated:
        send_content_under_review_email(
            email=episode.creator.email,
            episode_name=episode.title,
            creator_name=creator_display_name(episode.creator),
            episode_id=str(episode.id),
        )
        return True

    if episode.status == Episode.Status.REVIEW:
        return True

    logger.warning(
        "Could not move episode %s to REVIEW for public_id %s (status=%s)",
        episode_id,
        public_id,
        episode.status,
    )
    return False


def handle_cloudinary_eager_payload(payload: dict[str, Any]) -> str:
    if payload.get("notification_type") != "eager":
        return "ignored: not an eager notification"

    episode_id = resolve_episode_id(payload)
    public_id = payload.get("public_id")
    if not episode_id or not public_id:
        logger.warning("Eager webhook missing episode_id or public_id: %s", payload)
        return "ignored: missing episode_id or public_id"

    eager = payload.get("eager")
    if not isinstance(eager, list):
        eager = [eager] if eager else []

    if publish_episode_when_streaming_ready(episode_id, public_id, eager):
        return f"published episode {episode_id}"
    return f"no publish for episode {episode_id}"
