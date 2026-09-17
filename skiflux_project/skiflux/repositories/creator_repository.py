from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone

from skiflux.models import AdminUser, User
from skiflux.models.content import (
    Episode,
    EpisodePurchase,
    EpisodeRating,
    Follow,
    Season,
    TaskSubmission,
)
from skiflux.repositories.content_repository import ContentRepository


class CreatorRepository:
    def __init__(self):
        self.content_repo = ContentRepository()

    def get_by_id(self, creator_id: str) -> Optional[AdminUser]:
        try:
            return AdminUser.objects.filter(
                AdminUser.creators_filter(),
                id=creator_id,
                is_active=True,
            ).get()
        except AdminUser.DoesNotExist:
            return None

    def list_all(self):
        return AdminUser.objects.filter(
            AdminUser.creators_filter(),
            is_active=True,
        ).order_by("created_at")

    def get_analytics(self, creator: AdminUser) -> dict:

        today = timezone.localdate()

        start_of_this_month = today.replace(day=1)

        total_episodes = Episode.objects.filter(creator=creator).count()

        new_episodes_this_month = Episode.objects.filter(
            creator=creator,
            created_at__date__gte=start_of_this_month,
        ).count()

        episodes_growth_percentage = (
            (new_episodes_this_month / total_episodes) * 100
            if total_episodes > 0
            else 0
        )

        total_followers = Follow.objects.filter(creator=creator).count()

        new_followers_this_month = Follow.objects.filter(
            creator=creator,
            followed_at__date__gte=start_of_this_month,
        ).count()

        followers_growth_percentage = (
            (new_followers_this_month / total_followers) * 100
            if total_followers > 0
            else 0
        )

        earnings = EpisodePurchase.objects.filter(
            episode__creator=creator,
            status=EpisodePurchase.Status.ACTIVE,
        ).aggregate(total=Sum("amount_paid"))

        rating = EpisodeRating.objects.filter(episode__creator=creator).aggregate(
            avg=Avg("score"), count=Count("id")
        )

        avg_rating = rating["avg"]

        return {
            "total_episodes": total_episodes,
            "new_episodes_this_month": new_episodes_this_month,
            "episodes_growth_percentage": round(episodes_growth_percentage, 1),
            "total_followers": total_followers,
            "new_followers_this_month": new_followers_this_month,
            "followers_growth_percentage": round(followers_growth_percentage, 1),
            "total_earnings": earnings["total"] or Decimal("0.00"),
            "avg_rating": round(avg_rating, 1) if avg_rating is not None else None,
            "total_ratings": rating["count"] or 0,
        }

    def get_episodes(self, creator: AdminUser, status: Optional[str] = None):
        """Get episodes for a creator"""
        query = Episode.objects.filter(creator=creator).order_by("-created_at")
        if status:
            query = query.filter(status=status)
        return query.order_by("-created_at")

    def get_directory_stats(self) -> dict:
        today = timezone.localdate()
        start_of_this_month = today.replace(day=1)
        week_start = today - timedelta(days=today.weekday())
        week_end = today

        creator_qs = AdminUser.objects.filter(AdminUser.creators_filter())

        total_creators = creator_qs.count()

        new_this_month = creator_qs.filter(
            created_at__date__gte=start_of_this_month,
        ).count()

        growth_percentage = (
            (new_this_month / total_creators) * 100 if total_creators > 0 else 0
        )

        pending_submissions = TaskSubmission.objects.filter(
            status=TaskSubmission.Status.PENDING,
        ).count()

        avg_sla_rate = self.content_repo.get_average_sla_accross()

        active_today = creator_qs.filter(last_login__date=today).count()

        new_this_week = creator_qs.filter(
            created_at__date__gte=week_start,
            created_at__date__lte=week_end,
        ).count()

        weekly_uploads = (
            Episode.objects.filter(
                created_at__date__gte=week_start,
                created_at__date__lte=week_end,
            )
            .values("creator_id")
            .annotate(uploads=Count("id"))
        )

        if weekly_uploads.exists() and total_creators > 0:
            total_weekly = sum(w["uploads"] for w in weekly_uploads)
            avg_uploads = Decimal(str(total_weekly / total_creators)).quantize(
                Decimal("0.1")
            )
        else:
            avg_uploads = Decimal("0.0")

        return {
            "total_creators": total_creators,
            "new_creators_this_month": new_this_month,
            "growth_percentage_this_month": round(growth_percentage, 1),
            "active_today": active_today,
            "new_this_week": new_this_week,
            "avg_uploads_per_creator_this_week": avg_uploads,
            "pending_submissions": pending_submissions,
            "avg_sla_rate": avg_sla_rate,
        }

    def get_directory_list(
        self, search: str = None, status: str = None, date_from=None, date_to=None
    ):
        queryset = AdminUser.objects.filter(AdminUser.creators_filter()).order_by(
            "-created_at"
        )

        # --- filters ---
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(username__icontains=search)
            )

        if status is not None:
            queryset = queryset.filter(status=status)

        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        # --- annotations ---
        queryset = queryset.annotate(
            seasons_count=Count("seasons", distinct=True),
            episode_count=Count("episodes", distinct=True),
            earnings=Sum(
                "episodes__purchases__amount_paid",
                filter=Q(episodes__purchases__status=EpisodePurchase.Status.ACTIVE),
            ),
            pending_reviews=Count(
                "episodes",
                filter=Q(episodes__status=Episode.Status.REVIEW),
                distinct=True,
            ),
        )
        return queryset

    def get_creator_leaderboard(self, limit: int = 10):
        today = timezone.localdate()
        start_of_this_month = today.replace(day=1)

        queryset = (
            AdminUser.objects.filter(
                AdminUser.creators_filter(),
                status="active",
            )
            .annotate(
                episodes_count=Count("episodes", distinct=True),
                episodes_before_this_month=Count(
                    "episodes",
                    filter=Q(episodes__created_at__date__lt=start_of_this_month),
                    distinct=True,
                ),
            )
            .order_by("-episodes_count")[:limit]
        )

        leaderboard = []
        for rank, creator in enumerate(queryset, start=1):
            before = creator.episodes_before_this_month
            total = creator.episodes_count

            if before > 0:
                trend = Decimal(str(((total - before) / before) * 100)).quantize(
                    Decimal("0.1")
                )
            elif total > 0:
                trend = Decimal("100.0")  # All episodes are new, no prior baseline
            else:
                trend = Decimal("0.0")

            leaderboard.append(
                {
                    "rank": rank,
                    "first_name": creator.first_name,
                    "last_name": creator.last_name,
                    "username": creator.username,
                    "avatar_public_id": creator.avatar_public_id,
                    "episodes_count": total,
                    "episodes_count_trend_percentage": trend,
                }
            )

        return leaderboard

    def get_subscribers_count(self, creator: AdminUser) -> int:
        return Follow.objects.filter(creator=creator).count()

    def get_creator_audience_distribution(self, creator: AdminUser, limit: int = None):
        qs = (
            User.objects.filter(
                viewed_episodes__episode__creator=creator,
                country__isnull=False,
            )
            .exclude(country="")
            .values("country")
            .annotate(count=Count("id", distinct=True))
            .order_by("-count")
        )

        total = qs.aggregate(total=Sum("count"))["total"] or 0
        if not total:
            return []

        if limit:
            qs = qs[:limit]

        return [
            {
                "country": row["country"],
                "pct": round(row["count"] / total * 100),
            }
            for row in qs
        ]

    def get_creator_revenue_growth(
        self, creator: AdminUser, period: str = "week"
    ) -> dict:
        now = timezone.now()

        if period == "week":
            trunc = TruncDay
            current_start = now - timedelta(days=6)
            previous_start = current_start - timedelta(days=7)
            label_format = "%a"

        elif period == "month":
            trunc = TruncDay
            current_start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            previous_start = (current_start - timedelta(days=1)).replace(day=1)
            label_format = "%d"

        elif period == "year":
            trunc = TruncMonth
            current_start = now.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            previous_start = current_start.replace(year=current_start.year - 1)
            label_format = "%b"

        else:
            return {}

        def query(start, end):
            return (
                EpisodePurchase.objects.filter(
                    episode__creator=creator,
                    status=EpisodePurchase.Status.ACTIVE,
                    purchased_at__gte=start,
                    purchased_at__lte=end,
                )
                .annotate(bucket=trunc("purchased_at"))
                .values("bucket")
                .annotate(revenue=Sum("amount_paid"))
                .order_by("bucket")
            )

        def to_map(qs):
            return {
                row["bucket"].strftime(label_format): float(row["revenue"])
                for row in qs
            }

        current_map = to_map(query(current_start, now))
        previous_map = to_map(query(previous_start, current_start))

        all_labels = sorted(set(current_map) | set(previous_map))

        return {
            "labels": all_labels,
            "current": [current_map.get(label, 0) for label in all_labels],
            "previous": [previous_map.get(label, 0) for label in all_labels],
        }

    def _season_performance_annotations(self):
        return {
            "total_sales": Count(
                "episodes__purchases",
                filter=Q(episodes__purchases__status=EpisodePurchase.Status.ACTIVE),
                distinct=True,
            ),
            "revenue": Sum(
                "episodes__purchases__amount_paid",
                filter=Q(episodes__purchases__status=EpisodePurchase.Status.ACTIVE),
            ),
            "avg_rating": Avg("episodes__ratings__score"),
            "total_viewers": Count(
                "episodes__views__user",
                distinct=True,
            ),
            "completed_viewers": Count(
                "episodes__views__user",
                filter=Q(episodes__views__completed=True),
                distinct=True,
            ),
        }

    def get_creator_seasons_performance(self, creator: AdminUser):
        return (
            Season.objects.filter(creator=creator)
            .annotate(**self._season_performance_annotations())
            .order_by("-created_at")
        )

    def get_season_performance(self, creator: AdminUser, season_id: str):
        return (
            Season.objects.filter(creator=creator, id=season_id)
            .annotate(**self._season_performance_annotations())
            .first()
        )
