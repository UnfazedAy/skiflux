import logging

from skiflux.models import AdminUser, Episode, Season
from skiflux.models.activity import ActivityLog
from skiflux.repositories.content_repository import ContentRepository
from skiflux.services.activity import ActivityService
from skiflux.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class SeasonPublishService:
    """Publishes seasons automatically when they gain a published episode."""

    def __init__(self):
        self.content_repo = ContentRepository()

    def maybe_publish_season_for_episode(self, episode: Episode) -> bool:
        """
        When an episode becomes published, publish its season if needed.
        Follower notifications are sent only on the season's first publish.
        """
        if episode.status != Episode.Status.PUBLISHED:
            return False

        season = (
            Season.objects.select_related("creator")
            .filter(pk=episode.season_id)
            .first()
        )
        if not season or season.is_published:
            return False

        if not season.episodes.filter(status=Episode.Status.PUBLISHED).exists():
            return False

        season = self.content_repo.publish_season(season)
        self._notify_followers_new_season(season)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.SEASON_PUBLISHED,
            description=(
                f"Season '{season.title}' was published automatically "
                f"after episode '{episode.title}' went live."
            ),
            actor=season.creator,
            subject=season,
            metadata={"season_id": str(season.id), "title": season.title},
        )
        return True

    def _notify_followers_new_season(self, season: Season) -> None:
        creator = season.creator
        if not isinstance(creator, AdminUser):
            return
        try:
            followers = self.content_repo.get_followers_with_notifications(creator)
            notif = NotificationService()
            payload = {
                "season_id": str(season.id),
                "season_title": season.title,
                "skillworld": season.skillworld,
                "creator_id": str(creator.id),
            }
            title = f"New Season from {creator.first_name or creator.email}"
            body = f"'{season.title}' in {season.skillworld} is now available."
            for follower in followers:
                notif.create_notification(
                    user=follower,
                    type="new_season_from_followed_creator",
                    title=title,
                    body=body,
                    data=payload,
                )
                notif.send_push_for_event(
                    user=follower,
                    event_type="new_season_from_followed_creator",
                    title=title,
                    body=body,
                    data=payload,
                )
        except Exception:
            logger.warning(
                "Failed new_season_from_followed_creator notify (non-fatal)",
                exc_info=True,
            )
