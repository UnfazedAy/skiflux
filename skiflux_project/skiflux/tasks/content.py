import logging
import os
from datetime import time as dt_time
from datetime import timedelta

import cloudinary.api
import cloudinary.uploader
from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db.models import Max, Sum
from django.utils import timezone
from django.utils import timezone as dj_tz

from skiflux.models import (
    AssessmentSubmission,
    EpisodePurchase,
    TaskSubmission,
    TicketAttachment,
    User,
    UserBehaviourLog,
)
from skiflux.models.content import Episode, EpisodeResource
from skiflux.models.notification import PlatformAnnouncement
from skiflux.models.platform_settings import SystemNotificationConfig
from skiflux.repositories import (
    AdminUserRepository,
    ContentRepository,
    UserRepository,
)
from skiflux.services.episode_upload_service import (
    eager_list_has_hls,
    eager_transformation_failed,
    handle_cloudinary_eager_payload,
    publish_episode_when_streaming_ready,
    register_episode_public_id,
    set_episode_under_review,
)
from skiflux.services.notification_service import NotificationService
from skiflux.utils import get_private_media_url
from skiflux.utils.media import (
    creator_display_name,
    get_minio_presigned_url,
    send_content_failed_email,
    send_content_rejected_email,
    send_content_upload_received_email,
)

logger = logging.getLogger(__name__)


def attach_cloudinary_file(
    instance,
    *,
    public_id: str,
    field_public_id: str = "file_public_id",
    field_url: str = "file_url",
    content_type: str | None = None,
):
    """
    Standardized Cloudinary attachment handler for all non-video assets.
    """

    setattr(instance, field_public_id, public_id)

    # Decide resource type safely
    is_document = bool(content_type and content_type.startswith("application/"))

    resource_type = "raw" if is_document else "image"

    setattr(
        instance,
        field_url,
        get_private_media_url(public_id, resource_type=resource_type),
    )

    instance.save(update_fields=[field_public_id, field_url, "updated_at"])


@shared_task(bind=True, max_retries=5)
def upload_media_from_minio_task(
    self,
    instance_id,
    minio_object_key,
    field_name,
    model_name="Episode",
    resource_type="auto",
    review_mode=False,
    content_type=None,
):
    try:
        presigned_url = get_minio_presigned_url(minio_object_key)

        if model_name == "Episode":
            folder = "skiflux_content"
        elif model_name == "Season":
            folder = "skiflux_season_covers"
        elif model_name == "EpisodeComment":
            folder = "skiflux_comments"
        elif model_name == "TaskSubmission":
            folder = "skiflux_task_submissions"
        elif model_name == "TicketAttachment":
            folder = "skiflux_support_attachments"
        elif model_name == "EpisodeResource":
            folder = "skiflux_episode_resources"
        elif model_name == "Badge":
            folder = "skiflux_badges"
        else:
            folder = "skiflux_avatars"

        upload_kwargs = {
            "folder": folder,
            "type": "private",
            "resource_type": resource_type,
        }

        if resource_type == "video" and model_name == "Episode":
            upload_kwargs.update(
                {
                    "eager": [{"streaming_profile": "auto", "format": "m3u8"}],
                    "eager_async": True,
                }
            )
            upload_kwargs.update(_video_upload_options(instance_id))

        result = cloudinary.uploader.upload(presigned_url, **upload_kwargs)
        public_id = result.get("public_id")
        duration = result.get("duration")

        if model_name == "Episode":
            repo = ContentRepository()
            episode = repo.get_episode(instance_id)
            if not episode:
                return f"FAILED: Episode {instance_id} not found."

            if resource_type == "video":
                if duration is None:
                    if public_id:
                        cloudinary.uploader.destroy(
                            public_id, resource_type="video", type="private"
                        )

                    repo.update_episode_status(episode, Episode.Status.REJECTED)
                    reason = "Unable to verify video duration."
                    _notify_upload_rejected(instance_id, reason)
                    return f"REJECTED: {reason}"

                episode.video_public_id = public_id
                episode.video_duration = int(duration or 0)
                update_fields_list = ["video_public_id", "video_duration"]

                if not episode.thumbnail_public_id:
                    episode.thumbnail_public_id = public_id
                    update_fields_list.append("thumbnail_public_id")

                episode.save(update_fields=update_fields_list)
                repo.update_episode_status(episode, Episode.Status.PROCESSING)

                register_episode_public_id(instance_id, public_id)

                eager = result.get("eager") or []
                if eager_list_has_hls(eager):
                    if review_mode:
                        set_episode_under_review(instance_id, public_id, eager)
                    else:
                        publish_episode_when_streaming_ready(
                            instance_id, public_id, eager
                        )
                elif (
                    getattr(settings, "CLOUDINARY_EAGER_WEBHOOK_URL", "") or ""
                ).strip():
                    fallback_task = (
                        finalize_episode_review_fallback_task
                        if review_mode
                        else finalize_episode_streaming_fallback_task
                    )
                    fallback_task.apply_async(
                        args=[instance_id, public_id],
                        countdown=settings.CLOUDINARY_STREAMING_FALLBACK_DELAY_SECONDS,
                    )

                return f"Uploaded Episode Video: {public_id}"

            elif resource_type == "image":
                setattr(episode, field_name, public_id)
                episode.save(update_fields=[field_name])
                return f"Uploaded Episode Thumbnail: {public_id}"

        elif model_name == "AdminUser":
            repo = AdminUserRepository()
            admin = repo.get_by_id(instance_id)
            if admin:
                repo.update(admin, **{field_name: public_id})
                return f"Uploaded AdminUser Avatar: {public_id}"
            return f"FAILED: AdminUser {instance_id} not found."

        elif model_name == "User":
            repo = UserRepository()
            user = repo.get_by_id(instance_id)
            if user:
                repo.update(user, **{field_name: public_id})
                return f"Uploaded User Avatar: {public_id}"
            return f"FAILED: User {instance_id} not found."

        elif model_name == "Season":
            repo = ContentRepository()
            season = repo.get_season_by_id(instance_id)
            if not season:
                return f"FAILED: Season {instance_id} not found."

            if resource_type == "image":
                setattr(season, field_name, public_id)
                season.save(update_fields=[field_name])
                return f"Uploaded Season Cover: {public_id}"
            else:
                return f"ERROR: Season only supports image uploads, got {resource_type}"

        elif model_name == "EpisodeComment":
            from skiflux.models.content import EpisodeComment

            try:
                comment = EpisodeComment.objects.get(id=instance_id)
                setattr(comment, field_name, public_id)
                comment.save(update_fields=[field_name])
                return f"Uploaded EpisodeComment Audio: {public_id}"
            except EpisodeComment.DoesNotExist:
                return f"FAILED: EpisodeComment {instance_id} not found."

        elif model_name == "TaskSubmission":
            from skiflux.models.content import TaskSubmission
            from skiflux.utils.media import (
                cloudinary_resource_type_for_submission_file,
                get_private_media_url,
            )

            try:
                submission = TaskSubmission.objects.get(id=instance_id)
                resource_type = cloudinary_resource_type_for_submission_file(
                    submission.submission_file_content_type
                )
                submission.submission_file_public_id = public_id
                submission.submission_file_url = get_private_media_url(
                    public_id,
                    resource_type=resource_type,
                )
                submission.save(
                    update_fields=[
                        "submission_file_public_id",
                        "submission_file_url",
                    ]
                )
                return f"Uploaded TaskSubmission file: {public_id}"
            except TaskSubmission.DoesNotExist:
                return f"FAILED: TaskSubmission {instance_id} not found."

        elif model_name == "TicketAttachment":
            try:
                attachment = TicketAttachment.objects.get(id=instance_id)

                attach_cloudinary_file(
                    attachment,
                    public_id=public_id,
                    field_public_id="file_public_id",
                    field_url="file_url",
                    content_type=attachment.content_type,
                )

                attachment.is_processing = False
                attachment.save(update_fields=["is_processing", "updated_at"])

                return f"Uploaded TicketAttachment: {public_id}"

            except TicketAttachment.DoesNotExist:
                return f"FAILED: TicketAttachment {instance_id} not found."

        elif model_name == "EpisodeResource":
            try:
                resource = EpisodeResource.objects.get(id=instance_id)

                attach_cloudinary_file(
                    resource,
                    public_id=public_id,
                    field_public_id="file_public_id",
                    field_url="file_url",
                    content_type=resource.content_type,
                )

                resource.is_processing = False
                resource.save(update_fields=["is_processing", "updated_at"])

                return f"Uploaded EpisodeResource: {public_id}"

            except EpisodeResource.DoesNotExist:
                return f"FAILED: EpisodeResource {instance_id} not found."

        elif model_name == "Badge":
            from skiflux.models.gamification import Badge

            try:
                badge = Badge.objects.get(id=instance_id)
                setattr(badge, field_name, public_id)
                badge.save(update_fields=[field_name])
                return f"Uploaded Badge Icon: {public_id}"
            except Badge.DoesNotExist:
                return f"FAILED: Badge {instance_id} not found."

    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))

        if resource_type == "video" and model_name == "Episode":
            repo = ContentRepository()
            episode = repo.get_episode(instance_id)
            if episode:
                repo.update_episode_status(episode, Episode.Status.FAILED)
            _notify_upload_failed(instance_id, "Upload failed after multiple attempts.")
        raise


def _load_episode_for_notify(instance_id):
    try:
        return Episode.objects.select_related("creator").get(id=instance_id)
    except Episode.DoesNotExist:
        logger.warning(
            "Episode %s not found for upload notification; skipping email",
            instance_id,
        )
        return None


def _notify_upload_received(instance_id):
    episode = _load_episode_for_notify(instance_id)
    if not episode:
        return
    send_content_upload_received_email(
        email=episode.creator.email,
        episode_name=episode.title,
        creator_name=creator_display_name(episode.creator),
        episode_id=str(episode.id),
    )


def _notify_upload_rejected(instance_id, reason: str):
    episode = _load_episode_for_notify(instance_id)
    if not episode:
        return
    send_content_rejected_email(
        email=episode.creator.email,
        rejection_reason=reason,
        episode_name=episode.title,
        creator_name=creator_display_name(episode.creator),
        episode_id=str(episode.id),
    )


def _notify_upload_failed(instance_id, reason: str):
    episode = _load_episode_for_notify(instance_id)
    if not episode:
        return
    send_content_failed_email(
        email=episode.creator.email,
        failure_reason=reason,
        episode_name=episode.title,
        creator_name=creator_display_name(episode.creator),
        episode_id=str(episode.id),
    )


def _video_upload_options(instance_id: str) -> dict:
    options = {
        "context": {"episode_id": str(instance_id)},
    }
    webhook_url = (getattr(settings, "CLOUDINARY_EAGER_WEBHOOK_URL", "") or "").strip()
    if webhook_url:
        options["eager_notification_url"] = webhook_url
    return options


@shared_task
def process_cloudinary_eager_webhook_task(payload: dict):
    return handle_cloudinary_eager_payload(payload)


@shared_task(bind=True, max_retries=8)
def finalize_episode_streaming_fallback_task(self, instance_id, public_id):
    try:
        resource = cloudinary.api.resource(
            public_id,
            resource_type="video",
            type="private",
        )
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=120)
        logger.error(
            "Streaming fallback exhausted for episode %s; episode remains processing",
            instance_id,
            exc_info=True,
        )
        return "fallback exhausted"

    eager = resource.get("eager") or []
    failed, reason = eager_transformation_failed(eager)
    if failed:
        publish_episode_when_streaming_ready(instance_id, public_id, eager)
        return "Transcode failed; fallback aborted."
    if publish_episode_when_streaming_ready(instance_id, public_id, eager):
        return f"published episode {instance_id} via fallback"
    if self.request.retries < self.max_retries:
        raise self.retry(countdown=120)
    return "streaming not ready after fallback retries"


@shared_task(bind=True, max_retries=5)
def upload_media_from_path_task(
    self,
    instance_id,
    file_path,
    model_app,
    model_name,
    field_name,
    resource_type="auto",
    review_mode=False,
):
    try:
        upload_kwargs = {
            "folder": "skiflux_content",
            "type": "private",
            "resource_type": resource_type,
            "eager": [
                {
                    "streaming_profile": "auto",
                    "format": "m3u8",
                },
            ],
            "eager_async": True,
        }
        if resource_type == "video":
            upload_kwargs.update(_video_upload_options(instance_id))

        result = cloudinary.uploader.upload(file_path, **upload_kwargs)
        public_id = result.get("public_id")
        duration = result.get("duration")
        Model = apps.get_model(model_app, model_name)

        if resource_type == "video":
            if duration is None:
                if public_id:
                    cloudinary.uploader.destroy(
                        public_id, resource_type="video", type="private"
                    )
                Model.objects.filter(id=instance_id).update(
                    status=Episode.Status.REJECTED
                )
                _notify_upload_rejected(
                    instance_id,
                    "Unable to verify video duration. "
                    "Please upload a valid video file.",
                )
                return "REJECTED: Unable to verify video duration."

        update_fields = {field_name: public_id}
        if resource_type == "video":
            update_fields["status"] = Episode.Status.PROCESSING
            update_fields["video_duration"] = int(duration or 0)
            instance = Model.objects.get(id=instance_id)
            if not instance.thumbnail_public_id:
                update_fields["thumbnail_public_id"] = public_id
            Model.objects.filter(id=instance_id).update(**update_fields)
            register_episode_public_id(instance_id, public_id)
            _notify_upload_received(instance_id)

            eager = result.get("eager") or []
            if eager_list_has_hls(eager):
                if review_mode:
                    set_episode_under_review(instance_id, public_id, eager)
                else:
                    publish_episode_when_streaming_ready(instance_id, public_id, eager)
            elif (getattr(settings, "CLOUDINARY_EAGER_WEBHOOK_URL", "") or "").strip():
                fallback_task = (
                    finalize_episode_review_fallback_task
                    if review_mode
                    else finalize_episode_streaming_fallback_task
                )
                fallback_task.apply_async(
                    args=[instance_id, public_id],
                    countdown=settings.CLOUDINARY_STREAMING_FALLBACK_DELAY_SECONDS,
                )
            else:
                logger.warning(
                    "CLOUDINARY_EAGER_WEBHOOK_URL not set; "
                    "episode %s awaits manual publish",
                    instance_id,
                )

            return f"Uploaded {resource_type}: {public_id}"

        Model.objects.filter(id=instance_id).update(**update_fields)
        return f"Uploaded {resource_type}: {public_id}"
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
        if resource_type == "video":
            Model = apps.get_model(model_app, model_name)
            Model.objects.filter(id=instance_id).update(status=Episode.Status.FAILED)
            _notify_upload_failed(
                instance_id,
                "Upload failed after multiple attempts.",
            )
        raise
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


@shared_task(bind=True, max_retries=8)
def finalize_episode_review_fallback_task(self, instance_id, public_id):
    try:
        resource = cloudinary.api.resource(
            public_id,
            resource_type="video",
            type="private",
        )
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=120)
        logger.error(
            "Review fallback exhausted for episode %s; episode remains processing",
            instance_id,
            exc_info=True,
        )
        return "fallback exhausted"

    eager = resource.get("eager") or []
    failed, _ = eager_transformation_failed(eager)
    if failed:
        set_episode_under_review(instance_id, public_id, eager)
        return "Transcode failed; review fallback aborted."
    if set_episode_under_review(instance_id, public_id, eager):
        return f"moved episode {instance_id} to REVIEW via fallback"
    if self.request.retries < self.max_retries:
        raise self.retry(countdown=120)
    return "streaming not ready after review fallback retries"


@shared_task
def aggregate_behaviour_logs():
    from skiflux.models.user_behaviour_log import UserSkillworldScore

    scores = UserBehaviourLog.objects.values("user_id", "skillworld").annotate(
        total=Sum("weight")
    )
    for row in scores:
        UserSkillworldScore.objects.update_or_create(
            user_id=row["user_id"],
            skillworld=row["skillworld"],
            defaults={"total_weight": row["total"]},
        )
    cutoff = timezone.now() - timedelta(days=90)
    deleted, _ = UserBehaviourLog.objects.filter(created_at__lt=cutoff).delete()
    return f"Aggregated scores. Archived {deleted} old log entries."


@shared_task
def cleanup_cloudinary_asset_task(public_id: str, resource_type: str = "video") -> str:
    try:
        result = cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
            type="private",
        )
        logger.info(
            "Cleaned up orphaned Cloudinary asset %s: %s",
            public_id,
            result,
        )
        return f"destroyed: {public_id}"
    except Exception as e:
        logger.error(
            "Failed to cleanup Cloudinary asset %s: %s",
            public_id,
            e,
            exc_info=True,
        )
        return f"failed: {public_id}"


def _notify_inactive_users(inactive_users, today, notif_service):
    for user in inactive_users:
        last_active = UserBehaviourLog.objects.filter(user=user).aggregate(
            last=Max("created_at")
        )["last"]
        days_missed = 0
        if last_active:
            days_missed = (today - last_active.date()).days
        else:
            days_missed = 999

        title = "We miss you!"
        body = f"We haven't seen you for {days_missed} day(s). Come back and continue your learning journey!"  # noqa: E501
        if days_missed > 7:
            body = f"It's been {days_missed} days! We miss you — your learning streak is waiting."  # noqa: E501

        try:
            notif_service.create_notification(
                user=user,
                type="we_miss_you",
                title=title,
                body=body,
                data={"days_missed": days_missed},
            )
            notif_service.send_push_for_event(
                user=user,
                event_type="we_miss_you",
                title=title,
                body=body,
                data={"days_missed": days_missed},
            )
        except Exception:
            logger.warning("Failed streak_broken notify for user %s", user.id)

        try:
            streak = UserBehaviourLog.compute_current_streak(user)
            if streak >= 2:
                btitle = "Streak broken"
                bbody = f"Your {streak}-day streak ended after {days_missed} day(s) away. Start a new one!"  # noqa: E501
                notif_service.create_notification(
                    user=user,
                    type="streak_broken",
                    title=btitle,
                    body=bbody,
                    data={"previous_streak": streak, "days_missed": days_missed},
                )
                notif_service.send_push_for_event(
                    user=user,
                    event_type="streak_broken",
                    title=btitle,
                    body=bbody,
                    data={"previous_streak": streak, "days_missed": days_missed},
                )
        except Exception:
            logger.warning("Failed streak_broken notify for user %s", user.id)


def _send_task_reminders(notif_service) -> int:
    purchases = EpisodePurchase.objects.filter(
        status=EpisodePurchase.Status.ACTIVE
    ).select_related("episode", "user")

    pending_count = 0
    for p in purchases:
        episode = p.episode
        user = p.user
        if not user or not getattr(user, "is_active", False):
            continue

        project_approved = TaskSubmission.objects.filter(
            task__episode=episode, user=user, status=TaskSubmission.Status.APPROVED
        ).exists()
        assess_passed = AssessmentSubmission.objects.filter(
            task__episode=episode, user=user, passed=True
        ).exists()

        if not project_approved and not assess_passed:
            pending_count += 1
            title = f"Reminder: Complete tasks for {episode.title}"
            body = "You have purchased this episode but haven't completed the tasks yet. Earn your coins!"  # noqa: E501
            try:
                notif_service.create_notification(
                    user=user,
                    type="task_reminder",
                    title=title,
                    body=body,
                    data={
                        "episode_id": str(episode.id),
                        "episode_title": episode.title,
                    },
                )
                notif_service.send_push_for_event(
                    user=user,
                    event_type="task_reminder",
                    title=title,
                    body=body,
                    data={"episode_id": str(episode.id)},
                )
            except Exception:
                logger.warning(
                    "Failed task reminder for user %s episode %s", user.id, episode.id
                )
    return pending_count


def _process_daily_announcements(notif_service, now):
    try:
        now_local = dj_tz.localtime()
        current_minutes = now_local.hour * 60 + now_local.minute
        daily_anns = PlatformAnnouncement.objects.filter(
            send_type="daily",
            is_active=True,
        )
        for ann in daily_anns:
            if ann.daily_send_time:
                t = ann.daily_send_time
                ann_minutes = t.hour * 60 + t.minute
                if abs(current_minutes - ann_minutes) <= 15:
                    already_sent_today = False
                    if ann.last_sent_at:
                        last_sent_local = dj_tz.localtime(ann.last_sent_at)
                        if last_sent_local.date() == now_local.date():
                            already_sent_today = True

                    if not already_sent_today:
                        notif_service.send_platform_announcement(announcement=ann)
                        ann.last_sent_at = now
                        ann.save(update_fields=["last_sent_at"])
    except Exception:
        logger.warning("Daily ann re-broadcast check failed (non-fatal)")


@shared_task
def send_daily_reminders():
    now = dj_tz.now()
    today = now.date()
    notif_service = NotificationService()
    config = SystemNotificationConfig.get_config()
    target_time = config.daily_reminder_time or dt_time(9, 0)  # WAT local
    local_now = dj_tz.localtime(now)
    current = local_now.time()
    target_minutes = target_time.hour * 60 + target_time.minute
    current_minutes = current.hour * 60 + current.minute
    if abs(current_minutes - target_minutes) > 15:
        return "not reminder time yet"

    cache_key = f"daily_reminders_sent_{today.isoformat()}"
    if cache.get(cache_key):
        return "already sent today"

    cache.set(cache_key, True, timeout=86400)  # 24h

    active_today = (
        UserBehaviourLog.objects.filter(created_at__date=today)
        .values_list("user_id", flat=True)
        .distinct()
    )
    inactive_users = User.objects.filter(is_active=True).exclude(id__in=active_today)

    _notify_inactive_users(inactive_users, today, notif_service)
    pending_count = _send_task_reminders(notif_service)

    logger.info(
        "Daily reminders sent at configured time: miss_you=%s, task_reminders=%s",
        len(inactive_users),
        pending_count,
    )

    _process_daily_announcements(notif_service, now)

    return f"reminders: miss_you={len(inactive_users)}, tasks={pending_count}"
