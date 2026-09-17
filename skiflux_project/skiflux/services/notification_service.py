import logging
from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from skiflux.models.platform_settings import SystemNotificationConfig
from skiflux.models.user import UserDevice
from skiflux.tasks import send_push_notification_task
from skiflux.tasks.notification import fanout_platform_announcement_task


logger = logging.getLogger(__name__)


class NotificationService:
    EVENT_TITLES = {
        "task_approved_with_coins": "Task Approved",
        "task_rejected_with_feedback": "Task Needs Revision",
        "task_submission_received": "New Submission Received",
        "episode_approved": "Episode Approved",
        "episode_rejected": "Episode Review Update",
        "withdrawal_processed": "Withdrawal Processed",
        "new_episode_in_enrolled_world": "New Episode Available",
        "deposit_confirmed": "Deposit Confirmed",
        "platform_announcement": "Platform Announcement",
        "task_reminder": "Task Reminder",
        "followed_creator_new_episode": "New Episode from Creator You Follow",
        "we_miss_you": "We Miss You",
        "new_comment_on_episode": "New Comment on Your Episode",
        "milestone_badge_earned": "Milestone Achieved!",
        "new_follower": "New Follower",
        "assessment_perfect_score": "Perfect Score!",
        "new_season_from_followed_creator": "New Season from Followed Creator",
        "task_deadline_approaching": "Task Deadline Approaching",
        "referral_bonus_credited": "Referral Bonus Credited",
        "streak_broken": "Streak Broken",
        "streak_maintained": "Streak Maintained",
        "episode_reached_x_views": "Episode Milestone",
        "revenue_milestone": "Revenue Milestone",
        "new_learning_path": "New Learning Path Available",
        "community_challenge": "Community Challenge",
        "moderation_warning": "Community Guidelines Warning",
        "moderation_suspension": "Account Suspended",
        "moderation_suspension_lifted": "Suspension Lifted",
        "moderation_comment_removed": "Comment Removed",
        "ticket_assigned": "Ticket Assigned",
        "support_ticket_resolved": "Support Ticket Resolved",
    }

    def __init__(self):
        from skiflux.repositories.notification_repository import NotificationRepository

        self.repo = NotificationRepository()

    def register_device(
        self,
        user: Optional[Any] = None,
        admin_user: Optional[Any] = None,
        token: str = "",
        platform: str = "android",
        device_id: Optional[str] = None,
    ) -> UserDevice:
        if not token or len(str(token).strip()) < 10:
            raise ValidationError({"token": "A valid push token is required."})

        platform = (platform or "android").lower()
        if platform not in [p[0] for p in UserDevice.Platform.choices]:
            platform = "android"

        token = str(token).strip()

        if bool(user) == bool(admin_user):
            raise ValidationError(
                "Exactly one of user or admin_user must be provided "
                "for device registration."
            )

        defaults: dict[str, Any] = {
            "platform": platform,
            "device_id": device_id,
            "is_active": True,
        }
        if user:
            defaults["user"] = user
            device, created = self.repo.update_or_create_device(
                token=token, defaults=defaults
            )
            owner_filter = {"user": user}
        else:
            defaults["admin_user"] = admin_user
            device, created = self.repo.update_or_create_device(
                token=token, defaults=defaults
            )
            owner_filter = {"admin_user": admin_user}

        if device_id:
            self.repo.deactivate_other_devices(owner_filter, device_id, device.id)

        logger.info(
            "Device registered for push",
            extra={
                "user_id": str(getattr(user, "id", "")) or None,
                "admin_id": str(getattr(admin_user, "id", "")) or None,
                "platform": platform,
                "device_id": device_id,
                "created": created,
            },
        )
        return device

    def send_push_notification(
        self,
        user: Optional[Any] = None,
        admin_user: Optional[Any] = None,
        title: str = "",
        body: str = "",
        data: Optional[dict] = None,
        event_type: Optional[str] = None,
    ) -> int:
        if not title or not body:
            return 0

        if bool(user) == bool(admin_user):
            logger.debug("send_push_notification called without clear owner; skipped")
            return 0

        if event_type:
            try:
                config = SystemNotificationConfig.get_config()
                enabled = getattr(config, event_type, True)
                if not enabled:
                    logger.debug(
                        "Push suppressed by notification config",
                        extra={"event_type": event_type},
                    )
                    return 0
            except Exception:
                pass

        devices = []
        if user:
            devices = self.repo.get_active_devices_for_user(user, limit=15)
        else:
            devices = self.repo.get_active_devices_for_admin(admin_user, limit=15)

        count = 0
        payload_data = dict(data or {})
        if event_type:
            payload_data.setdefault("event_type", event_type)

        for dev in devices:
            try:
                send_push_notification_task.delay(
                    token=dev.token,
                    title=title,
                    body=body,
                    data=payload_data,
                    platform=dev.platform,
                    device_id=dev.device_id,
                )
                count += 1
            except Exception:
                logger.exception("Failed to enqueue push task for device")
        if count:
            logger.info(
                "Enqueued push notifications",
                extra={
                    "owner": "user" if user else "admin",
                    "count": count,
                    "event_type": event_type,
                    "title": title[:60],
                },
            )
        return count

    def send_push_for_event(
        self,
        user: Optional[Any] = None,
        admin_user: Optional[Any] = None,
        event_type: str = "",
        title: Optional[str] = None,
        body: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> int:
        if not event_type:
            return 0

        # check user notification preferences — only for regular users
        # admin_user notifications are never preference-gated
        if user:
            try:
                from skiflux.models.notification_preference import (
                    UserNotificationPreferences,
                )

                prefs = UserNotificationPreferences.get_or_create_for_user(user)
                if not prefs.allows(event_type):
                    logger.debug(
                        "Push suppressed by user preference: user=%s event=%s",
                        getattr(user, "id", "?"),
                        event_type,
                    )
                    return 0
            except Exception:
                # never block a notification due to a prefs error
                logger.warning(
                    "Failed to check notification preferences for user=%s event=%s",
                    getattr(user, "id", "?"),
                    event_type,
                )

        t = title or self.EVENT_TITLES.get(event_type, "SkiFlux Update")
        b = body or "You have a new update."
        count = self.send_push_notification(
            user=user,
            admin_user=admin_user,
            title=t,
            body=b,
            data=data,
            event_type=event_type,
        )
        if count:
            from skiflux.models.notification import Notification as NotificationModel

            try:
                self.create_notification(
                    user=user,
                    admin_user=admin_user,
                    type=event_type,
                    title=t,
                    body=b,
                    data=data,
                    delivery_channel=NotificationModel.DeliveryChannel.BACKGROUND,
                    delivery_status=NotificationModel.DeliveryStatus.SENT,
                )
            except Exception:
                logger.warning(
                    "Failed to persist background notification row (non-fatal)",
                    exc_info=True,
                )
        return count

    def create_notification(
        self,
        *,
        user=None,
        admin_user=None,
        type: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        delivery_channel: str | None = None,
        delivery_status: str | None = None,
        audience: str = "",
        scheduled_at=None,
    ):
        from skiflux.models.notification import Notification as NotificationModel

        if bool(user) == bool(admin_user):
            logger.warning("create_notification called without clear recipient")
            return None

        notif = self.repo.create_notification(
            user=user,
            admin_user=admin_user,
            type=type,
            title=title,
            body=body,
            data=data or {},
            delivery_channel=delivery_channel
            or NotificationModel.DeliveryChannel.FOREGROUND,
            delivery_status=delivery_status or NotificationModel.DeliveryStatus.SENT,
            audience=audience or "",
            scheduled_at=scheduled_at,
        )
        return notif

    def send_platform_announcement(
        self,
        announcement: Any,
        send_push: bool = True,
    ):

        payload = {
            "announcement_id": str(announcement.id),
            "title": announcement.title,
            "body": announcement.body,
            "image_public_id": announcement.image_public_id,
            "send_type": announcement.send_type,
            "delivery_channel": getattr(announcement, "delivery_channel", "foreground"),
            "audience": getattr(announcement, "audience", "All users"),
        }

        from skiflux.models.notification import Notification as NotificationModel

        is_daily = announcement.send_type == "daily"
        if is_daily:
            scheduled_at = None
            if announcement.daily_send_time and announcement.created_by:
                from datetime import datetime, timedelta

                from django.utils import timezone as dj_tz

                now = dj_tz.localtime()
                send_time = announcement.daily_send_time
                candidate = dj_tz.make_aware(
                    datetime.combine(now.date(), send_time),
                    timezone=now.tzinfo,
                )
                if candidate <= now:
                    candidate = dj_tz.make_aware(
                        datetime.combine(
                            now.date() + timedelta(days=1),
                            send_time,
                        ),
                        timezone=now.tzinfo,
                    )
                scheduled_at = candidate

            self.create_notification(
                admin_user=announcement.created_by,
                type="platform_announcement",
                title=announcement.title,
                body=announcement.body,
                data=payload,
                delivery_channel=getattr(
                    announcement, "delivery_channel", "foreground"
                ),
                delivery_status=NotificationModel.DeliveryStatus.PENDING,
                audience=getattr(announcement, "audience", "All users"),
                scheduled_at=scheduled_at,
            )
            return True

        fanout_platform_announcement_task.delay(
            announcement_id=str(announcement.id),
            title=announcement.title,
            body=announcement.body,
            payload=payload,
        )
        if send_push:
            try:
                self.send_platform_announcement_push(
                    title=announcement.title,
                    body=announcement.body[:200]
                    if len(announcement.body) > 200
                    else announcement.body,
                    data=payload,
                )
            except Exception:
                logger.warning("Platform announcement push failed (non-fatal)")

        return True

    def _build_notification_obj(self, **kwargs):
        from skiflux.models.notification import Notification

        return Notification(**kwargs)

    def get_user_notifications(self, user, unread_only=False, offset=0, limit=20):
        return self.get_notifications(
            user=user, unread_only=unread_only, offset=offset, limit=limit
        )

    def get_admin_notifications(
        self, admin_user, unread_only=False, offset=0, limit=20
    ):
        return self.get_notifications(
            admin_user=admin_user, unread_only=unread_only, offset=offset, limit=limit
        )

    def get_notifications(
        self, *, user=None, admin_user=None, unread_only=False, offset=0, limit=20
    ):

        if bool(user) == bool(admin_user):
            logger.warning("get_notifications called without clear recipient")
            return {"total": 0, "items": [], "offset": offset, "limit": limit}

        if user:
            qs = self.repo.get_notifications_for_user(user)
        else:
            qs = self.repo.get_notifications_for_admin(admin_user)

        if unread_only:
            qs = qs.filter(is_read=False)

        total = qs.count()
        items = list(qs[offset : offset + limit])

        results = []
        for n in items:
            results.append(
                {
                    "id": str(n.id),
                    "type": n.type,
                    "title": n.title,
                    "body": n.body,
                    "data": n.data,
                    "is_read": n.is_read,
                    "created_at": n.created_at.isoformat(),
                }
            )

        return {"total": total, "items": results, "offset": offset, "limit": limit}

    def mark_notification_read(
        self, notification_id: str, *, user=None, admin_user=None
    ):
        if not user and not admin_user:
            raise ValidationError("Must provide user or admin_user.")

        if user:
            n = self.repo.get_notification_for_user(notification_id, user)
        else:
            n = self.repo.get_notification_for_admin(notification_id, admin_user)

        if not n:
            raise ValidationError("Notification not found.")

        if not n.is_read:
            n.is_read = True
            n.save(update_fields=["is_read"])

    def mark_all_notifications_read(self, *, user=None, admin_user=None) -> int:
        if not user and not admin_user:
            raise ValidationError("Must provide user or admin_user.")
        return self.repo.mark_all_notifications_read(user=user, admin_user=admin_user)

    def send_platform_announcement_push(
        self,
        title: str,
        body: str,
        data: Optional[dict] = None,
        topic: str = "platform_announcements",
    ) -> bool:
        payload_data = dict(data or {})
        payload_data.setdefault("event_type", "platform_announcement")

        try:
            send_push_notification_task.delay(
                token=None,
                title=title,
                body=body,
                data=payload_data,
                platform=None,
                topic=topic,
            )
            logger.info(
                "Enqueued platform announcement to topic",
                extra={"topic": topic, "title": title[:60]},
            )
            return True
        except Exception:
            logger.exception("Failed to enqueue platform announcement push")
            return False

    def get_admin_notification_stats(self) -> dict:
        stats = self.repo.get_notification_stats()
        return {
            "total_sent": stats.get("total_sent") or 0,
            "total_foreground": stats.get("total_foreground") or 0,
            "total_background": stats.get("total_background") or 0,
            "scheduled_pending": stats.get("scheduled_pending") or 0,
        }

    def get_admin_notification_history_queryset(
        self, delivery_filter: str | None = None
    ):
        return self.repo.get_grouped_notification_history(delivery_filter)

    def serialize_notification_history_rows(self, rows) -> list[dict]:
        results = []
        for row in rows:
            results.append(
                {
                    "title": row["title"],
                    "message": row["body"],
                    "type": row["delivery_channel"],
                    "audience": row["audience"] or "All users",
                    "send_time": row["send_time"],
                    "status": row["delivery_status"],
                    "recipient_count": row["recipient_count"],
                }
            )
        return results
