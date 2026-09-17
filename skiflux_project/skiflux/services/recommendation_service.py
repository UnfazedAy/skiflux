from datetime import timedelta

from django.db.models import (
    Case,
    IntegerField,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Random
from django.utils import timezone

from skiflux.models import User
from skiflux.models.content import Episode, EpisodeView
from skiflux.models.user_behaviour_log import UserBehaviourLog
from skiflux.repositories.content_repository import episodes_for_serializer


class RecommendationService:
    NEW_CONTENT_DAYS = 7
    MAX_RECOMMENDATION_SCORE = 100
    NEW_CONTENT_BOOST = 30

    # base score for content outside user's preferred skillworlds
    # keeps exploration alive — non-zero means it can surface occasionally
    EXPLORATION_BASE_SCORE = 8

    WEIGHTS = {
        UserBehaviourLog.Action.VIEW: 1.0,
        UserBehaviourLog.Action.LIKE: 2.5,
        UserBehaviourLog.Action.SAVE: 3.5,
        UserBehaviourLog.Action.COMMENT: 2.0,
        UserBehaviourLog.Action.TASK_ATTEMPT: 4.0,
        UserBehaviourLog.Action.TASK_COMPLETE: 5.0,
    }

    def get_queryset_for_user(
        self,
        user: User,
        seen_ids: list = None,
        exclude_completed: bool = True,
    ):
        from skiflux.models.app_preference import UserAppPreferences
        from skiflux.repositories.content_repository import ContentRepository

        prefs = UserAppPreferences.get_or_create_for_user(user)
        if not prefs.personalised_recommendations:
            qs = (
                episodes_for_serializer()
                .filter(status=Episode.Status.PUBLISHED, season__is_published=True)
                .order_by("-created_at", "id")
            )
            if exclude_completed:
                completed_ids = EpisodeView.objects.filter(
                    user=user,
                    completed=True,
                ).values_list("episode_id", flat=True)
                qs = qs.exclude(id__in=completed_ids)
            if seen_ids:
                qs = qs.exclude(id__in=seen_ids)
            content_repo = ContentRepository()
            not_interested_ids = content_repo.get_not_interested_episode_ids(user)
            if not_interested_ids:
                qs = qs.exclude(id__in=not_interested_ids)
            return qs

        content_repo = ContentRepository()

        # ── 1. Score skillworlds from behaviour logs ──
        scored_worlds = (
            content_repo.get_user_behaviour_logs(user)
            .values("skillworld")
            .annotate(total=Sum("weight"))
            .order_by("-total")
        )

        score_map = {
            row["skillworld"]: min(
                int(row["total"]),
                self.MAX_RECOMMENDATION_SCORE,
            )
            for row in scored_worlds
        }

        # ── 2. Cold start — use onboarding skillworld preferences ──
        if not score_map and user.skillworld:
            for skillworld in user.skillworld:
                score_map[skillworld] = 50

        # ── 3. Build recommendation score cases ──
        recommendation_cases = [
            When(
                season__skillworld=skillworld,
                then=Value(score),
            )
            for skillworld, score in score_map.items()
        ]

        # ── 4. Freshness boost ──
        new_cutoff = timezone.now() - timedelta(days=self.NEW_CONTENT_DAYS)

        # ── 5. Base queryset ──
        qs = (
            episodes_for_serializer()
            .filter(status=Episode.Status.PUBLISHED)
            .annotate(
                recommendation_score=Case(
                    *recommendation_cases,
                    # non-preferred content gets a small base score
                    # so it occasionally surfaces — exploration factor
                    default=Value(self.EXPLORATION_BASE_SCORE),
                    output_field=IntegerField(),
                ),
                freshness_score=Case(
                    When(
                        created_at__gte=new_cutoff,
                        then=Value(self.NEW_CONTENT_BOOST),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
                # random jitter so same-scored episodes shuffle on reload
                random_score=Random(),
            )
            .order_by(
                "-recommendation_score",
                "-freshness_score",
                "-random_score",
                "id",
            )
        )

        # ── 6. Exclude completed episodes ──
        # only hides episodes the user fully watched (completed=True)
        # partial watches still appear so users can continue them
        if exclude_completed:
            completed_ids = EpisodeView.objects.filter(
                user=user,
                completed=True,
            ).values_list("episode_id", flat=True)
            qs = qs.exclude(id__in=completed_ids)

        # ── 7. Exclude session-seen IDs (passed from frontend) ──
        # frontend tracks IDs shown in current scroll session
        # and passes them to prevent immediate repeats
        if seen_ids:
            qs = qs.exclude(id__in=seen_ids)

        # ── 8. Exclude episodes the user marked as not interested ──
        not_interested_ids = content_repo.get_not_interested_episode_ids(user)
        if not_interested_ids:
            qs = qs.exclude(id__in=not_interested_ids)

        return qs
