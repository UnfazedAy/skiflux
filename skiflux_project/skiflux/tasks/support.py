from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="skiflux.tasks.support.poll_support_inbox",
)
def poll_support_inbox(self):
    from skiflux.services.support_email_service import fetch_support_emails

    try:
        result = fetch_support_emails(limit=20)
        logger.info(f"poll_support_inbox: {result}")
        return result
    except Exception as exc:
        logger.error(f"poll_support_inbox failed: {exc}")
        raise self.retry(exc=exc)
