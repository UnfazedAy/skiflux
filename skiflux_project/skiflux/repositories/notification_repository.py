from typing import Optional

from django.db.models import Count, Max, Q
from django.db.models.functions import Coalesce

from skiflux.models import Notification, UserDevice
from skiflux.models.admin_user import AdminUser
from skiflux.models.notification import Notification as NotificationModel
from skiflux.models.user import User


class NotificationRepository:
    def update_or_create_device(
        self, token: str, defaults: dict
    ) -> tuple[UserDevice, bool]:
        return UserDevice.objects.update_or_create(token=token, defaults=defaults)

    def deactivate_other_devices(
        self, owner_filter: dict, device_id: str, exclude_id: str
    ):
        UserDevice.objects.filter(
            **owner_filter,
            device_id=device_id,
            is_active=True,
        ).exclude(id=exclude_id).update(is_active=False)

    def deactivate_devices(self, token: str):
        UserDevice.objects.filter(token=token).update(is_active=False)

    def get_active_devices_for_user(self, user: User, limit: int = 15):
        return list(UserDevice.objects.filter(user=user, is_active=True)[:limit])

    def get_active_devices_for_admin(self, admin_user: AdminUser, limit: int = 15):
        return list(
            UserDevice.objects.filter(admin_user=admin_user, is_active=True)[:limit]
        )

    def create_notification(self, **kwargs) -> Notification:
        delivery_channel = kwargs.pop("delivery_channel", None)
        delivery_status = kwargs.pop("delivery_status", None)
        audience = kwargs.pop("audience", "")
        scheduled_at = kwargs.pop("scheduled_at", None)

        from skiflux.models.notification import Notification as NotificationModel

        notification = Notification.objects.create(
            **kwargs,
            delivery_channel=delivery_channel
            or NotificationModel.DeliveryChannel.FOREGROUND,
            delivery_status=delivery_status or NotificationModel.DeliveryStatus.SENT,
            audience=audience or "",
            scheduled_at=scheduled_at,
        )
        return notification

    def get_notifications_for_user(self, user: User):
        return Notification.objects.filter(user=user)

    def get_notifications_for_admin(self, admin_user: AdminUser):
        return Notification.objects.filter(admin_user=admin_user)

    def get_notification_for_user(
        self, notification_id: str, user: User
    ) -> Optional[Notification]:
        try:
            return Notification.objects.get(id=notification_id, user=user)
        except Notification.DoesNotExist:
            return None

    def get_notification_for_admin(
        self, notification_id: str, admin_user: AdminUser
    ) -> Optional[Notification]:
        try:
            return Notification.objects.get(id=notification_id, admin_user=admin_user)
        except Notification.DoesNotExist:
            return None

    def mark_all_notifications_read(
        self,
        *,
        user: User = None,
        admin_user: AdminUser = None,
    ) -> int:
        if user:
            return Notification.objects.filter(user=user, is_read=False).update(
                is_read=True
            )
        if admin_user:
            return Notification.objects.filter(
                admin_user=admin_user,
                is_read=False,
            ).update(is_read=True)
        return 0

    def get_notification_stats(self) -> dict:
        sent = NotificationModel.DeliveryStatus.SENT
        pending = NotificationModel.DeliveryStatus.PENDING
        foreground = NotificationModel.DeliveryChannel.FOREGROUND
        background = NotificationModel.DeliveryChannel.BACKGROUND

        return Notification.objects.aggregate(
            total_sent=Count("id", filter=Q(delivery_status=sent)),
            total_foreground=Count(
                "id",
                filter=Q(delivery_status=sent, delivery_channel=foreground),
            ),
            total_background=Count(
                "id",
                filter=Q(delivery_status=sent, delivery_channel=background),
            ),
            scheduled_pending=Count("id", filter=Q(delivery_status=pending)),
        )

    def get_grouped_notification_history(self, delivery_filter: str | None = None):
        qs = Notification.objects.all()
        sent = NotificationModel.DeliveryStatus.SENT
        pending = NotificationModel.DeliveryStatus.PENDING
        foreground = NotificationModel.DeliveryChannel.FOREGROUND
        background = NotificationModel.DeliveryChannel.BACKGROUND

        if delivery_filter == "foreground":
            qs = qs.filter(delivery_channel=foreground, delivery_status=sent)
        elif delivery_filter == "background":
            qs = qs.filter(delivery_channel=background, delivery_status=sent)
        elif delivery_filter == "scheduled":
            qs = qs.filter(delivery_status=pending)

        return (
            qs.values(
                "title",
                "body",
                "delivery_channel",
                "audience",
                "delivery_status",
                "scheduled_at",
            )
            .annotate(
                send_time=Coalesce("scheduled_at", Max("created_at")),
                recipient_count=Count("id"),
            )
            .order_by("-send_time")
        )
