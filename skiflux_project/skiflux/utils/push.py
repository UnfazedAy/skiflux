import logging
import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
import json
from skiflux.models.user import UserDevice


logger = logging.getLogger(__name__)

if not firebase_admin._apps:
    if settings.FIREBASE_SERVICE_ACCOUNT:
        cred = credentials.Certificate(json.loads(settings.FIREBASE_SERVICE_ACCOUNT))
    else:
        cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)


def send_fcm_push(
    token: str = None,
    title: str = "",
    body: str = "",
    data: dict = None,
    platform: str = None,
    topic: str = None,
) -> tuple[bool, str]:
    _ = platform
    if not data:
        data = {}
    str_data = {str(k): str(v) for k, v in data.items()}
    try:
        message_kwargs = {
            "notification": messaging.Notification(title=title, body=body),
            "data": str_data,
            "android": messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(sound="default"),
            ),
            "apns": messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            ),
        }
        if topic:
            message = messaging.Message(topic=topic, **message_kwargs)
        elif token:
            message = messaging.Message(token=token, **message_kwargs)
        else:
            return False, "missing_target"
        response = messaging.send(message)
        logger.info(f"Successfully sent message: {response}")
        return True, response
    except messaging.UnregisteredError:
        return False, "invalid_token"
    except Exception as e:
        logger.error(f"FCM Push failed: {str(e)}", exc_info=True)
        return False, str(e)


def get_active_devices_for_user(user) -> list:
    if not user or not getattr(user, "id", None):
        return []
    return list(
        UserDevice.objects.filter(user=user, is_active=True).order_by("-last_seen_at")[
            :20
        ]
    )


def get_active_devices_for_admin(admin_user) -> list:
    if not admin_user or not getattr(admin_user, "id", None):
        return []
    return list(
        UserDevice.objects.filter(admin_user=admin_user, is_active=True).order_by(
            "-last_seen_at"
        )[:20]
    )


def deactivate_bad_token(token: str, reason: str = ""):
    UserDevice.objects.filter(token=token).update(is_active=False)
    logger.info(f"Deactivated FCM token due to {reason}: {token[:15]}")
