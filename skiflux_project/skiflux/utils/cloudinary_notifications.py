import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def verify_cloudinary_notification(request) -> bool:
    timestamp = request.headers.get("X-Cld-Timestamp", "")
    signature = request.headers.get("X-Cld-Signature", "")
    if not timestamp or not signature:
        return False
    try:
        import cloudinary.utils

        cloudinary.utils.verify_notification_signature(
            request.body,
            timestamp,
            signature,
            valid_for=settings.CLOUDINARY_WEBHOOK_TOLERANCE_SECONDS,
        )
        return True
    except Exception:
        logger.warning("Cloudinary notification signature verification failed")
        return False


def parse_cloudinary_notification_body(request) -> dict:
    content_type = request.content_type or ""
    if "application/json" in content_type:
        return json.loads(request.body.decode("utf-8"))
    if request.POST:
        return request.POST.dict()
    if request.body:
        try:
            return json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            pass
    return {}
