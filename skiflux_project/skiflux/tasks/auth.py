import logging

import requests

# import resend
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# from django.core.mail import send_mail


# @shared_task(bind=True, max_retries=3)
# def send_app_email_task_smtp(
#     self,
#     subject: str,
#     message: str,
#     recipient_email: str,
#     html_message: str = None,
# ):

#     from_email = getattr(
#         settings, "DEFAULT_FROM_EMAIL", "Skiflux <noreply@skiflux.com>"
#     )

#     try:
#         send_mail(
#             subject=subject,
#             message=message,
#             from_email=from_email,
#             recipient_list=[recipient_email],
#             html_message=html_message,
#             fail_silently=False,
#         )
#         return f"Successfully sent email to {recipient_email}"

#     except Exception as exc:
#         raise self.retry(exc=exc, countdown=60)


# @shared_task(bind=True, max_retries=3)
# def send_app_email_task_resend(
#     self,
#     subject: str,
#     message: str,
#     recipient_email: str,
#     html_message: str = None,
# ):
#     resend.api_key = settings.RESEND_API_KEY
#     try:
#         params = {
#             "from": settings.DEFAULT_FROM_EMAIL,
#             "to": [recipient_email],
#             "subject": subject,
#             "text": message,
#         }
#         if html_message:
#             params["html"] = html_message
#         resend.Emails.send(params)
#         return f"Successfully sent email to {recipient_email}"
#     except Exception as exc:
#         raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=5)
def send_app_email_task(
    self,
    subject: str,
    message: str,
    recipient_email: str,
    html_message: str = None,
):
    url = "https://api.brevo.com/v3/smtp/email"

    payload = {
        "sender": {"name": "SkiFlux", "email": settings.DEFAULT_FROM_EMAIL},
        "to": [{"email": recipient_email}],
        "subject": subject,
        "textContent": message,
    }

    if html_message:
        payload["htmlContent"] = html_message
    headers = {
        "accept": "application/json",
        "api-key": settings.BREVO_API_KEY,
        "content-type": "application/json",
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(
            "Brevo email sent",
            extra={"recipient_email": recipient_email, "subject": subject},
        )
        return f"Successfully sent email to {recipient_email}"

    except Exception as exc:
        status_code = None
        response_body = None
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status_code = exc.response.status_code
            response_body = exc.response.text
        logger.error(
            "Brevo email failed",
            extra={
                "recipient_email": recipient_email,
                "subject": subject,
                "status_code": status_code,
                "response_body": response_body,
                "error": str(exc),
            },
        )
        countdown = 60 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


@shared_task
def cleanup_expired_blacklisted_tokens():
    from skiflux.models import BlacklistedToken

    deleted_count, _ = BlacklistedToken.objects.filter(
        expires_at__lt=timezone.now()
    ).delete()
    return f"Deleted {deleted_count} expired blacklisted tokens."


@shared_task(bind=True, max_retries=3)
def send_push_notification_task(
    self,
    token: str = None,
    title: str = "",
    body: str = "",
    data: dict | None = None,
    platform: str | None = None,
    device_id: str | None = None,
    topic: str = None,
):
    _ = device_id
    from skiflux.utils.push import deactivate_bad_token, send_fcm_push

    success, info = send_fcm_push(
        token=token, title=title, body=body, data=data, platform=platform, topic=topic
    )

    if success:
        target = (
            f"topic={topic}" if topic else f"token={token[:12] if token else 'n/a'}..."
        )
        return f"push_sent {target}"

    if topic:
        if info in ("no_fcm_key",) or (
            isinstance(info, str) and info.startswith("http_4")
        ):
            return f"push_topic_skipped reason={info}"
        countdown = 30 * (2**self.request.retries)
        raise self.retry(
            exc=Exception(f"push_topic_transient_{info}"), countdown=countdown
        )

    # per-token logic
    terminal_errors = {
        "NotRegistered",
        "InvalidRegistration",
        "MismatchSenderId",
        "no_fcm_key",
        "invalid_token",
    }
    if info in terminal_errors or (isinstance(info, str) and info.startswith("http_4")):
        deactivate_bad_token(token, reason=str(info))
        return f"push_skipped_deactivated reason={info}"

    countdown = 30 * (2**self.request.retries)
    logger.info(
        "Push will retry",
        extra={"token_prefix": token[:12], "retry": self.request.retries, "info": info},
    )
    raise self.retry(exc=Exception(f"push_transient_{info}"), countdown=countdown)
