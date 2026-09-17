from celery import shared_task
from skiflux.repositories.moderation_repository import ModerationRepository
from skiflux.models.content import EpisodeComment
from skiflux.services.ai.gemini_moderator import GeminiModerator
from skiflux.services.moderation_service import ModerationService


@shared_task
def expire_due_suspensions():
    count = ModerationRepository().expire_due_suspensions()
    return f"Expired {count} suspensions."


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def moderate_comment_task(comment_id: str):

    try:
        comment = EpisodeComment.objects.get(id=comment_id)
    except EpisodeComment.DoesNotExist:
        return

    if comment.flagged:
        return

    if not comment.text or not comment.text.strip():
        return

    moderator = GeminiModerator()

    result = moderator.moderate(comment.text)

    if not result["flagged"]:
        return

    ModerationService().handle_ai_flag(
        comment=comment,
        reason=result["reason"],
        confidence=result["confidence"],
        # auto_suspend=result["confidence"] >= 0.98,
    )
