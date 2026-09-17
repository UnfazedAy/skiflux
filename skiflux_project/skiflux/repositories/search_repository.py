from django.db.models import Q

from skiflux.models import AdminUser, Episode, Season, User


class SearchRepository:
    def get_search_querysets(self, query: str):
        episodes = Episode.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            status=Episode.Status.PUBLISHED,
        ).select_related("season", "creator")

        seasons = Season.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            is_published=True,
        ).select_related("creator")

        creators = AdminUser.objects.filter(
            AdminUser.creators_filter(),
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query),
            is_active=True,
        )

        users = User.objects.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query),
            is_active=True,
        )

        return {
            "episodes": episodes,
            "seasons": seasons,
            "creators": creators,
            "users": users,
        }
