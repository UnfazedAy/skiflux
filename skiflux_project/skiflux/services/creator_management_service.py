from typing import Optional

from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from skiflux.models.admin_user import AdminUser
from skiflux.models.content import Episode
from skiflux.repositories import AdminUserRepository
from skiflux.repositories.content_repository import ContentRepository
from skiflux.repositories.creator_repository import CreatorRepository
from skiflux.utils import get_private_avatar_url

ANALYTICS_CACHE_TTL = 60 * 2
DIRECTORY_STATS_CACHE_TTL = 60 * 2


class CreatorManagementService:
    def __init__(self):
        self.creator_repo = CreatorRepository()
        self.admin_user_repo = AdminUserRepository()
        self.content_repo = ContentRepository()

    def _get_creator_or_raise(self, creator_id: str) -> AdminUser:
        creator = self.creator_repo.get_by_id(creator_id)
        if not creator or not creator.is_listed_creator:
            raise ValidationError("Creator not found.")
        return creator

    def invalidate_creator_analytics_cache(self, creator_id: str):
        cache.delete(f"creator_analytics_{creator_id}")

    def list_creators(self, admin_user: None):
        return self.creator_repo.list_all()

    def get_creator_oversight(self, admin_user: None, creator_id: str):
        creator = self.creator_repo.get_by_id(creator_id)
        if not creator:
            raise ValidationError("Creator not found.")

        episodes = self.content_repo.get_episodes_by_creator(creator)
        return creator, episodes

    def get_creator_profile(self, admin_user: None, creator_id: str):
        creator = self.creator_repo.get_by_id(creator_id)
        if not creator or not creator.is_listed_creator:
            raise ValidationError("Creator not found.")

        seasons = self.content_repo.get_seasons_by_creator(creator)
        episodes = self.content_repo.get_episodes_by_creator(creator)

        return {
            "id": str(creator.id),
            "email": creator.email,
            "username": creator.username,
            "first_name": creator.first_name,
            "last_name": creator.last_name,
            "display_name": creator.display_name,
            "bio": creator.bio,
            "avatar_url": get_private_avatar_url(creator.avatar_public_id),
            "role_type": creator.role_type,
            "is_active": creator.is_active,
            "is_verified": creator.is_verified,
            "created_at": creator.created_at,
            "updated_at": creator.updated_at,
            "stats": {
                "seasons_count": seasons.count(),
                "episodes_count": episodes.count(),
                "submissions_count": self.content_repo.get_submissions_count_by_creator(
                    creator
                ),
                "subscribers_count": self.get_subscribers_count(creator.id),
                "sla_avg": self.content_repo.get_average_sla_by_creator(creator),
            },
        }

    def override_episode(
        self,
        creator_id: str,
        episode_id: str,
        action: str,
    ):
        creator = self._get_creator_or_raise(creator_id)
        episode = self.content_repo.get_episode(episode_id, creator)

        if not episode:
            raise ValidationError("Episode not found for this creator.")

        if action == "unpublish":
            return self.content_repo.update_episode_status(
                episode, Episode.Status.DRAFT
            )

        raise ValidationError("Invalid action.")

    def get_creator_analytics(self, creator_id: str) -> dict:
        cache_key = f"creator_analytics_{creator_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        creator = self._get_creator_or_raise(creator_id)
        analytics = self.creator_repo.get_analytics(creator)
        cache.set(cache_key, analytics, ANALYTICS_CACHE_TTL)
        return analytics

    def get_creator_episodes(self, creator_id: str, status: Optional[str] = None):
        creator = self._get_creator_or_raise(creator_id)
        return self.creator_repo.get_episodes(creator, status=status)

    def get_directory_stats(self) -> dict:
        cache_key = "creator_directory_stats"
        cached = cache.get(cache_key)
        if cached:
            return cached
        stats = self.creator_repo.get_directory_stats()
        cache.set(cache_key, stats, DIRECTORY_STATS_CACHE_TTL)
        return stats

    def get_directory_list(
        self,
        search: str = None,
        status: Optional[str] = None,
        date_from=None,
        date_to=None,
    ):
        return self.creator_repo.get_directory_list(
            search=search,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )

    def invalidate_directory_stats_cache(self):
        cache.delete("creator_directory_stats")

    def get_subscribers_count(self, creator_id: str) -> int:
        creator = self._get_creator_or_raise(creator_id)
        return self.creator_repo.get_subscribers_count(creator)

    def get_creator_audience_distribution(
        self, creator_id: str, limit: int = None
    ) -> list:
        creator = self.creator_repo.get_by_id(creator_id)
        if not creator:
            raise ValidationError("Creator not found.")

        if creator.status == AdminUser.Status.SUSPENDED:
            raise ValidationError("This creator account is suspended.")

        if creator.status == AdminUser.Status.DEACTIVATED:
            raise ValidationError("This creator account is deactivated.")

        if not creator.is_active:
            raise ValidationError("This creator account is no longer active.")

        return self.creator_repo.get_creator_audience_distribution(creator, limit=limit)

    def get_creator_revenue_growth(self, creator_id: str, period: str = "week") -> dict:
        creator = self.creator_repo.get_by_id(creator_id)
        if not creator:
            raise ValidationError("Creator not found.")

        if creator.status == AdminUser.Status.SUSPENDED:
            raise ValidationError("This creator account is suspended.")

        if creator.status == AdminUser.Status.DEACTIVATED:
            raise ValidationError("This creator account is deactivated.")

        if not creator.is_active:
            raise ValidationError("This creator account is no longer active.")

        return self.creator_repo.get_creator_revenue_growth(creator, period)

    def get_creator_seasons_performance(self, creator_id: str):
        creator = self.creator_repo.get_by_id(creator_id)
        if not creator:
            raise ValidationError("Creator not found.")
        return self.creator_repo.get_creator_seasons_performance(creator)
