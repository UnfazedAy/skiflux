from celery import shared_task
import logging
from skiflux.models import User, AdminUser
from skiflux.models.notification import Notification

logger = logging.getLogger(__name__)


@shared_task
def fanout_platform_announcement_task(
    announcement_id: str, title: str, body: str, payload: dict
):
    delivery_channel = payload.get("delivery_channel", "foreground")
    audience = payload.get("audience", "")
    user_iterator = User.objects.filter(is_active=True).iterator(chunk_size=2000)
    notifs_batch = []

    for user in user_iterator:
        notifs_batch.append(
            Notification(
                user=user,
                type="platform_announcement",
                title=title,
                body=body,
                data=payload,
                delivery_channel=delivery_channel,
                delivery_status=Notification.DeliveryStatus.SENT,
                audience=audience,
            )
        )

        if len(notifs_batch) >= 2000:
            Notification.objects.bulk_create(notifs_batch, ignore_conflicts=True)
            notifs_batch = []

    if notifs_batch:
        Notification.objects.bulk_create(notifs_batch, ignore_conflicts=True)

    admin_iterator = AdminUser.objects.filter(is_active=True).iterator(chunk_size=500)
    notifs_batch = []
    for admin in admin_iterator:
        notifs_batch.append(
            Notification(
                admin_user=admin,
                type="platform_announcement",
                title=title,
                body=body,
                data=payload,
                delivery_channel=delivery_channel,
                delivery_status=Notification.DeliveryStatus.SENT,
                audience=audience,
            )
        )
    if notifs_batch:
        Notification.objects.bulk_create(notifs_batch, ignore_conflicts=True)

    logger.info(f"Platform announcement fanout completed for {announcement_id}")
