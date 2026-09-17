from datetime import timedelta
from decimal import Decimal
from typing import Optional
import uuid

from django.db import IntegrityError
from django.db.models import (
    Count,
    DurationField,
    ExpressionWrapper,
    F,
    Prefetch,
    Q,
    Max,
)
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from skiflux.models import (
    AdminUser,
    AssessmentQuestion,
    AssessmentSubmission,
    Episode,
    EpisodeComment,
    EpisodePurchase,
    EpisodeRating,
    EpisodeTask,
    EpisodeView,
    Follow,
    Season,
    TaskSubmission,
    User,
    UserBehaviourLog,
)
from skiflux.models.platform_settings import SystemContentConfig


def episodes_for_serializer(*, extra_filter=None):
    creator_qs = AdminUser.objects.annotate(
        followers_count=Count("followers", distinct=True)
    )
    qs = (
        Episode.objects.select_related("season")
        .annotate(
            like_count=Count("liked_by", distinct=True),
            comment_count=Count("comments", distinct=True),
            save_count=Count("save_later", distinct=True),
        )
        .prefetch_related(
            Prefetch("creator", queryset=creator_qs),
            "tasks",
        )
    )
    if extra_filter is not None:
        qs = qs.filter(extra_filter)
    return qs


class ContentRepository:
    def _calculate_sla_percentage(self, queryset) -> float:
        sla_hours = SystemContentConfig.get_config().sla_review_hours
        sla_cutoff = timezone.now() - timedelta(hours=sla_hours)

        base_qs = queryset.filter(
            created_at__lte=sla_cutoff,
        )

        total = base_qs.count()

        if total == 0:
            return 0

        reviewed_on_time = base_qs.filter(
            reviewed_at__isnull=False,
            reviewed_at__lte=F("created_at") + timedelta(hours=sla_hours),
        ).count()

        return round((reviewed_on_time / total) * 100, 1)

    def get_next_episode_order(self, season: Season) -> int:
        """Next available order number for episodes in this season."""
        max_order = Episode.objects.filter(season=season).aggregate(
            max_order=Max("order")
        )["max_order"]
        return (max_order or 0) + 1

    def create_season(
        self,
        creator: AdminUser,
        title: str,
        description: str,
        skillworld: str,
    ) -> Season:
        return Season.objects.create(
            creator=creator,
            title=title,
            description=description,
            skillworld=skillworld,
        )

    def get_season(
        self,
        season_id: str,
        creator: AdminUser = None,
    ) -> Optional[Season]:
        try:
            qs = Season.objects.get(id=season_id)
            if creator and qs.creator != creator:
                return None
            return qs
        except Season.DoesNotExist:
            return None

    def get_sla_avg_for_season(self, season: Season) -> float:
        qs = TaskSubmission.objects.filter(
            task__episode__season=season,
            task__kind=EpisodeTask.Kind.PROJECT_BASED,
        )
        return self._calculate_sla_percentage(qs)

    def get_average_sla_by_creator(self, creator: AdminUser) -> float:
        qs = TaskSubmission.objects.filter(
            task__episode__creator=creator,
            task__kind=EpisodeTask.Kind.PROJECT_BASED,
        )
        return self._calculate_sla_percentage(qs)

    def get_average_sla_accross(self) -> float:
        qs = TaskSubmission.objects.filter(
            task__kind=EpisodeTask.Kind.PROJECT_BASED,
        )
        return self._calculate_sla_percentage(qs)

    def get_seasons_by_creator(self, creator: AdminUser):
        return (
            Season.objects.filter(creator=creator)
            .prefetch_related("episodes")
            .annotate(
                episodes_count=Count("episodes", distinct=True),
                submission_count=(
                    Count("episodes__tasks__submissions", distinct=True)
                    + Count("episodes__tasks__assessment_submissions", distinct=True)
                ),
            )
        )

    def get_creator_season_count(self, creator: AdminUser) -> int:
        return Season.objects.filter(creator=creator).count()

    def get_episode_count_by_season(self, season: Season) -> int:
        return Episode.objects.filter(season=season).count()

    def get_submissions_count_by_creator(self, creator: AdminUser) -> int:
        """Reusable standalone query for a creator's total submission count."""
        result = TaskSubmission.objects.filter(
            task__episode__creator=creator,
            task__kind=EpisodeTask.Kind.PROJECT_BASED,
        ).aggregate(
            task_submissions=Count("id", distinct=True),
        )
        assessment_result = AssessmentSubmission.objects.filter(
            task__episode__creator=creator,
        ).aggregate(
            assessment_submissions=Count("id", distinct=True),
        )
        return (result["task_submissions"] or 0) + (
            assessment_result["assessment_submissions"] or 0
        )

    def get_submission_count_for_season(self, season: Season) -> int:
        """Reusable standalone query for a single season's submission count."""
        result = TaskSubmission.objects.filter(
            task__episode__season=season,
            task__kind=EpisodeTask.Kind.PROJECT_BASED,
        ).aggregate(
            task_submissions=Count("id", distinct=True),
        )
        assessment_result = AssessmentSubmission.objects.filter(
            task__episode__season=season,
        ).aggregate(
            assessment_submissions=Count("id", distinct=True),
        )
        return (result["task_submissions"] or 0) + (
            assessment_result["assessment_submissions"] or 0
        )

    def publish_season(self, season: Season) -> Season:
        season.is_published = True
        season.save(update_fields=["is_published", "updated_at"])
        return season

    def create_episode(
        self,
        creator: AdminUser,
        season: Season,
        title: str,
        description: str,
        order: Optional[int] = None,
        access_type: str = Episode.AccessType.PAID,
        submitted_for_review: bool = False,
    ) -> Episode:
        status = (
            Episode.Status.REVIEW if submitted_for_review else Episode.Status.PROCESSING
        )
        submitted_at = timezone.now() if submitted_for_review else None

        if order is None:
            order = self.get_next_episode_order(season)

        try:
            return Episode.objects.create(
                creator=creator,
                season=season,
                title=title,
                description=description,
                order=order,
                access_type=access_type,
                status=status,
                submitted_for_review_at=submitted_at,
            )
        except IntegrityError:
            raise ValidationError(
                {"order": ("An episode with this order already exists in this season.")}
            )

    def get_episode(
        self, episode_id: str, creator: AdminUser = None
    ) -> Optional[Episode]:
        try:
            ep = (
                Episode.objects.select_related("season")
                .prefetch_related("resources")
                .get(id=episode_id)
            )
            if creator and ep.creator != creator:
                return None
            return ep
        except Episode.DoesNotExist:
            return None

    def get_episodes_by_creator(self, creator: AdminUser):
        return episodes_for_serializer().filter(creator=creator).order_by("-created_at")

    def get_published_episodes_by_skillworld(self, skillworld: str):
        return Episode.objects.filter(
            season__skillworld=skillworld,
            status=Episode.Status.PUBLISHED,
        ).select_related("season", "creator")

    def update_episode_status(
        self,
        episode: Episode,
        status: str,
    ) -> Episode:
        episode.status = status
        episode.save(update_fields=["status", "updated_at"])
        return episode

    def get_episode_by_status(self, status: Optional[str] = None):
        if status:
            return Episode.objects.filter(status=status).order_by("-created_at")
        return Episode.objects.all().order_by("-created_at")

    def get_episode_count(
        self,
        season: Season | None = None,
        status: str | None = None,
    ) -> int:
        qs = Episode.objects.all()

        if season is not None:
            qs = qs.filter(season=season)

        if status is not None:
            qs = qs.filter(status=status)

        return qs.count()

    def get_season_total_view(self, season: Season) -> int:
        return EpisodeView.objects.filter(episode__season=season).count()

    def get_episode_total_view(self, episode: Episode) -> int:
        return EpisodeView.objects.filter(episode=episode).count()

    def create_behaviour_log(self, user, episode, season, skillworld, action, weight):

        return UserBehaviourLog.objects.create(
            user=user,
            episode=episode,
            season=season,
            skillworld=skillworld,
            action=action,
            weight=weight,
        )

    def get_user_behaviour_logs(self, user):

        return UserBehaviourLog.objects.filter(user=user)

    def get_user_viewed_episode_ids(self, user):
        return EpisodeView.objects.filter(user=user).values_list(
            "episode_id", flat=True
        )

    def get_completed_tasks_count(self, user):

        return UserBehaviourLog.objects.filter(
            user=user, action=UserBehaviourLog.Action.TASK_COMPLETE
        ).count()

    def get_user_project_submission(self, task, user):
        try:
            return TaskSubmission.objects.get(task=task, user=user)
        except TaskSubmission.DoesNotExist:
            return None

    def get_user_assessment_submissions(self, *args, **kwargs):

        if args and (
            isinstance(args[0], EpisodeTask)
            or getattr(args[0], "__class__", __name__).__name__ == "EpisodeTask"
        ):
            task = args[0]
            user = args[1] if len(args) > 1 else kwargs.get("user")
            limit = args[2] if len(args) > 2 else kwargs.get("limit", 5)

            return list(
                AssessmentSubmission.objects.filter(task=task, user=user).order_by(
                    "-attempt_number"
                )[:limit]
            )

        user = args[0] if len(args) > 0 else kwargs.get("user")
        status = args[1] if len(args) > 1 else kwargs.get("status")
        skillworld = args[2] if len(args) > 2 else kwargs.get("skillworld")
        episode_id = args[3] if len(args) > 3 else kwargs.get("episode_id")

        qs = (
            AssessmentSubmission.objects.filter(user=user)
            .select_related("task__episode__season", "task__episode")
            .order_by("-submitted_at")
        )
        if status:
            if status == "passed":
                qs = qs.filter(passed=True)
            elif status in ("failed", "not_passed"):
                qs = qs.filter(passed=False)
            else:
                qs = qs.none()
        if skillworld:
            qs = qs.filter(task__episode__season__skillworld=skillworld)
        if episode_id:
            qs = qs.filter(task__episode_id=episode_id)
        return qs

    def has_awarded_cashback_for_assessment(self, task, user):
        return AssessmentSubmission.objects.filter(
            task=task, user=user, cashback_amount__gt=0
        ).exists()

    def get_task_submission_for_review(self, submission_id: str):
        try:
            return TaskSubmission.objects.select_related(
                "user", "task__episode__season"
            ).get(id=submission_id)
        except TaskSubmission.DoesNotExist:
            return None

    def get_episode_with_creator(self, episode_id: str):
        return Episode.objects.select_related("creator").filter(id=episode_id).first()

    def transition_episode_status(
        self, episode_id: str, public_id: str, from_status: str, to_status: str
    ):
        return Episode.objects.filter(
            id=episode_id,
            video_public_id=public_id,
            status=from_status,
        ).update(status=to_status)

    def mark_episode_uploaded(self, episode_id: str, raw_video_id: str):
        return Episode.objects.filter(
            id=episode_id, status=Episode.Status.DRAFT
        ).update(
            raw_video_id=raw_video_id,
            status=Episode.Status.PROCESSING,
        )

    def mark_episode_processed(
        self, episode_id: str, hls_playlist_id: str, duration: int
    ):
        return Episode.objects.filter(
            id=episode_id, status=Episode.Status.PROCESSING
        ).update(
            hls_playlist_id=hls_playlist_id,
            duration=duration,
            status=Episode.Status.PUBLISHED,
        )

    def get_episodes_for_bulk_review(self, episode_ids: list):
        return Episode.objects.filter(id__in=episode_ids, status=Episode.Status.REVIEW)

    def get_season_tasks_with_stats(self, season: Season):
        return (
            EpisodeTask.objects.filter(episode__season=season)
            .select_related("episode")
            .annotate(
                total_project_submissions=Count("submissions", distinct=True),
                total_assessment_submissions=Count(
                    "assessment_submissions", distinct=True
                ),
                pending_project_submissions=Count(
                    "submissions",
                    filter=Q(submissions__status=TaskSubmission.Status.PENDING),
                    distinct=True,
                ),
            )
            .order_by("episode__order", "created_at")
        )

    def get_season_comments(self, season: Season, flagged: bool = None):

        qs = (
            EpisodeComment.objects.filter(episode__season=season)
            .select_related("user", "episode")
            .order_by("-created_at")
        )
        if flagged is not None:
            qs = qs.filter(flagged=flagged)
        return qs

    def get_tasks_for_episodes(self, episodes):
        return EpisodeTask.objects.filter(episode__in=episodes)

    def get_task_submissions_count(self, tasks):
        return TaskSubmission.objects.filter(task__in=tasks).count()

    def get_assessment_submissions_count(self, tasks):
        return AssessmentSubmission.objects.filter(task__in=tasks).count()

    def get_task_submissions_by_episode(self, episode: Episode):
        return (
            TaskSubmission.objects.filter(task__episode=episode)
            .select_related("user", "task")
            .order_by("-created_at")
        )

    def get_assessment_submissions_by_episode(self, episode: Episode):
        return (
            AssessmentSubmission.objects.filter(task__episode=episode)
            .select_related("user", "task")
            .order_by("-submitted_at")
        )

    def get_task_submissions_count_by_episode(self, episode: Episode):
        return TaskSubmission.objects.filter(task__episode=episode).count()

    def get_assessment_submissions_count_by_episode(self, episode: Episode):
        return AssessmentSubmission.objects.filter(task__episode=episode).count()

    def get_pending_task_submissions_count_by_episode(self, episode: Episode):
        return TaskSubmission.objects.filter(
            task__episode=episode, status=TaskSubmission.Status.PENDING
        ).count()

    def get_task_by_id_and_episode(self, task_id: str, episode: Episode):
        return EpisodeTask.objects.filter(id=task_id, episode=episode).first()

    def get_task_submissions_by_task(self, task: EpisodeTask):
        return (
            TaskSubmission.objects.filter(task=task)
            .select_related("user", "reviewed_by")
            .order_by("-created_at")
        )

    def get_pending_task_submissions_for_creator(self, creator: AdminUser):
        return (
            TaskSubmission.objects.filter(
                task__episode__creator=creator,
                task__kind=EpisodeTask.Kind.PROJECT_BASED,
                status=TaskSubmission.Status.PENDING,
            )
            .select_related(
                "user",
                "task",
                "task__episode",
                "task__episode__season",
            )
            .order_by("created_at")
        )

    def get_task_submission(self, submission_id: str, task: EpisodeTask):
        try:
            return TaskSubmission.objects.get(id=submission_id, task=task)
        except TaskSubmission.DoesNotExist:
            return None

    def get_paginated_comments(self, episode: Episode, flagged: bool = False):
        qs = self.get_comments(episode).order_by("-created_at")
        if flagged:
            qs = qs.filter(flagged=True)
        return qs

    def get_season_stats(self, season_id: str) -> dict:
        season = Season.objects.filter(id=season_id).first()
        episode_count = season.episodes.count()
        total_views = self.get_season_total_view(season)
        total_submissions = self.get_submission_count_for_season(season)
        pending_review = self.get_episode_count(
            season=season, status=Episode.Status.REVIEW
        )

        return {
            "total_episodes": episode_count,
            "total_views": total_views,
            "total_submissions": total_submissions,
            "pending_review": pending_review,
        }

    def get_creator_by_id(self, creator_id: str) -> Optional[AdminUser]:
        try:
            return AdminUser.objects.get(id=creator_id)
        except AdminUser.DoesNotExist:
            return None

    def get_episodes_by_season(self, season_id: str):
        episodes = (
            Episode.objects.filter(season_id=season_id)
            .select_related("season")
            .prefetch_related("tasks")
            .order_by("order")
            .annotate(
                total_views=Count("views", distinct=True),
                project_submissions=Count(
                    "tasks__submissions",
                    filter=Q(tasks__kind="project_based"),
                    distinct=True,
                ),
                assessment_submissions=Count(
                    "tasks__assessment_submissions",
                    filter=Q(tasks__kind="assessment"),
                    distinct=True,
                ),
                pending_submissions=Count(
                    "tasks__submissions",
                    filter=Q(tasks__submissions__status="pending"),
                    distinct=True,
                ),
            )
        )
        return episodes

    def get_most_viewed_today(self) -> Optional[Episode]:
        return Episode.objects.order_by("-view_count").first()

    def get_task_by_kind(self, episode: Episode, kind: str) -> Optional[EpisodeTask]:
        try:
            return EpisodeTask.objects.get(episode=episode, kind=kind)
        except EpisodeTask.DoesNotExist:
            return None

    def get_profile_data(self, user):
        watch_preview_qs = (
            EpisodeView.objects.filter(user=user)
            .select_related("episode__season", "episode__creator")
            .order_by("-viewed_at")[:3]
        )

        return {
            "watch_preview": list(watch_preview_qs),
        }

    def create_task(
        self,
        episode,
        kind,
        sla_time_limit_hours=24,
        completion_criteria=None,
        task_brief=None,
        accepted_proof_types=None,
        pass_score_percent=None,
        time_limit_minutes=None,
        max_attempts=None,
    ):
        return EpisodeTask.objects.create(
            episode=episode,
            kind=kind,
            sla_time_limit_hours=sla_time_limit_hours or 24,
            completion_criteria=completion_criteria or {},
            task_brief=task_brief or "",
            accepted_proof_types=accepted_proof_types or [],
            pass_score_percent=pass_score_percent,
            time_limit_minutes=time_limit_minutes,
            max_attempts=max_attempts,
        )

    def update_task(self, task: EpisodeTask, **fields) -> EpisodeTask:
        for field, value in fields.items():
            setattr(task, field, value)
        task.save(update_fields=list(fields.keys()))
        return task

    def replace_assessment_questions(self, task: EpisodeTask, questions_data: list):

        AssessmentQuestion.objects.filter(task=task).delete()
        questions = [
            AssessmentQuestion(task=task, **q_data) for q_data in questions_data
        ]
        AssessmentQuestion.objects.bulk_create(questions)

    def upsert_view(
        self,
        user,
        episode,
        watch_duration_seconds: int,
        completed: bool,
    ):
        view, created = EpisodeView.objects.update_or_create(
            user=user,
            episode=episode,
            defaults={
                "watch_duration_seconds": watch_duration_seconds,
                "completed": completed,
            },
        )
        if created:
            Episode.objects.filter(id=episode.id).update(view_count=F("view_count") + 1)
        return view

    def toggle_like(self, user, episode: Episode) -> bool:
        """Toggles the like status. Returns True if liked, False if unliked."""
        if episode.liked_by.filter(id=user.id).exists():
            episode.liked_by.remove(user)
            return False
        episode.liked_by.add(user)
        return True

    def toggle_save(self, user, episode: Episode) -> bool:
        if episode.save_later.filter(id=user.id).exists():
            episode.save_later.remove(user)
            return False
        episode.save_later.add(user)
        return True

    def mark_not_interested(self, user, episode: Episode) -> bool:
        from skiflux.models.content import EpisodeNotInterested

        _, created = EpisodeNotInterested.objects.get_or_create(
            user=user,
            episode=episode,
        )
        return created

    def get_not_interested_episode_ids(self, user) -> list:
        from skiflux.models.content import EpisodeNotInterested

        return list(
            EpisodeNotInterested.objects.filter(user=user).values_list(
                "episode_id",
                flat=True,
            )
        )

    def add_comment(
        self,
        user,
        episode: Episode,
        text: str = "",
        parent: EpisodeComment | None = None,
    ):
        return EpisodeComment.objects.create(
            user=user,
            episode=episode,
            text=text,
            parent=parent,
        )

    def get_comment_by_id(self, comment_id: int) -> Optional[EpisodeComment]:
        try:
            return EpisodeComment.objects.select_related("user", "episode").get(
                id=comment_id
            )
        except EpisodeComment.DoesNotExist:
            return None

    def toggle_comment_like(self, user, comment: EpisodeComment) -> bool:
        if comment.liked_by.filter(id=user.id).exists():
            comment.liked_by.remove(user)
            return False
        comment.liked_by.add(user)
        return True

    def update_comment(self, comment: EpisodeComment, text: str) -> EpisodeComment:
        comment.text = text
        comment.save(update_fields=["text", "updated_at"])
        return comment

    def delete_comment(self, comment: EpisodeComment) -> None:
        comment.delete()

    def get_comments(self, episode: Episode):
        return (
            EpisodeComment.objects.filter(episode=episode, parent__isnull=True)
            .select_related("user")
            .prefetch_related(
                Prefetch(
                    "replies",
                    queryset=EpisodeComment.objects.select_related("user")
                    .prefetch_related("liked_by")
                    .order_by("created_at"),
                ),
                "liked_by",
            )
        )

    def get_task(self, task_id: str) -> Optional[EpisodeTask]:
        try:
            return EpisodeTask.objects.select_related("episode__season").get(id=task_id)
        except EpisodeTask.DoesNotExist:
            return None

    def get_tasks_for_viewed_episodes(self, user):

        return (
            EpisodeTask.objects.filter(episode__views__user=user)
            .select_related("episode__season")
            .annotate(viewed_at=F("episode__views__viewed_at"))
            .prefetch_related(
                Prefetch(
                    "submissions",
                    queryset=TaskSubmission.objects.filter(user=user).select_related(
                        "reviewed_by"
                    ),
                    to_attr="current_user_submissions",
                ),
                Prefetch(
                    "assessment_submissions",
                    queryset=AssessmentSubmission.objects.filter(user=user).order_by(
                        "-submitted_at"
                    ),
                    to_attr="current_user_assessment_submissions",
                ),
                Prefetch(
                    "questions",
                    queryset=AssessmentQuestion.objects.order_by("order"),
                    to_attr="prefetched_questions",
                ),
            )
            .order_by("-episode__views__viewed_at", "created_at")
        )

    def create_submission(
        self,
        task: EpisodeTask,
        user,
        submission_text: str = "",
        submission_url: str = None,
        submission_file_name: str = None,
        submission_file_content_type: str = None,
    ) -> TaskSubmission:
        return TaskSubmission.objects.create(
            task=task,
            user=user,
            submission_text=submission_text or "",
            submission_url=submission_url,
            submission_file_name=submission_file_name,
            submission_file_content_type=submission_file_content_type,
        )

    def mark_submission_rejected(
        self,
        submission: "TaskSubmission",
        reviewer: "AdminUser",
        reason: str,
        feedback: str = None,
    ) -> "TaskSubmission":
        from django.utils import timezone as dj_timezone

        from skiflux.models.content import TaskSubmission as _TaskSub

        submission.status = _TaskSub.Status.REJECTED
        submission.rejection_reason = reason
        submission.reviewed_by = reviewer
        submission.reviewed_at = dj_timezone.now()
        if feedback is not None:
            submission.feedback = feedback
        update_fields = ["status", "rejection_reason", "reviewed_by", "reviewed_at"]
        if feedback is not None:
            update_fields.append("feedback")
        submission.save(update_fields=update_fields)
        return submission

    def submission_exists(self, user, task: EpisodeTask) -> bool:
        return TaskSubmission.objects.filter(user=user, task=task).exists()

    def get_submission(self, submission_id: str) -> Optional[TaskSubmission]:
        try:
            return TaskSubmission.objects.select_related(
                "user", "task__episode__season"
            ).get(id=submission_id)
        except TaskSubmission.DoesNotExist:
            return None

    def create_assessment_submission(
        self,
        task: EpisodeTask,
        user,
        score_percent: float,
        passed: bool,
        answers: dict,
        attempt_number: int,
        cashback_amount: float = 0,
        time_taken_seconds: int = None,
    ):

        return AssessmentSubmission.objects.create(
            task=task,
            user=user,
            score_percent=score_percent,
            passed=passed,
            answers=answers,
            attempt_number=attempt_number,
            cashback_amount=cashback_amount,
            time_taken_seconds=time_taken_seconds,
        )

    def get_assessment_attempt_count(self, user, task: EpisodeTask) -> int:

        return AssessmentSubmission.objects.filter(user=user, task=task).count()

    def toggle_follow(self, user, creator) -> tuple:
        from skiflux.models.content import Follow

        follow, created = Follow.objects.get_or_create(
            follower=user,
            creator=creator,
            defaults={
                "notifications_enabled": True,
                "notification_mode": Follow.NotificationMode.ALL,
            },
        )
        if not created:
            follow.delete()
            return False  # unfollowed
        return True  # followed

    def get_followers_count(self, creator) -> int:
        return Follow.objects.filter(creator=creator).count()

    def get_followers_with_notifications(self, creator):
        from skiflux.models.content import Follow

        follower_ids = (
            Follow.objects.filter(creator=creator)
            .exclude(notification_mode=Follow.NotificationMode.NONE)
            .values_list("follower_id", flat=True)
        )
        return User.objects.filter(id__in=follower_ids, is_active=True)

    def get_follow(self, user, creator):
        return Follow.objects.filter(follower=user, creator=creator).first()

    def update_creator_notification_mode(self, user, creator, mode: str):
        from skiflux.models.content import Follow

        follow = Follow.objects.filter(follower=user, creator=creator).first()
        if not follow:
            return None
        follow.notification_mode = mode
        follow.notifications_enabled = mode != Follow.NotificationMode.NONE
        follow.save(update_fields=["notification_mode", "notifications_enabled"])
        return follow

    def is_following(self, user, creator) -> bool:
        return Follow.objects.filter(follower=user, creator=creator).exists()

    def get_followed_creators(self, user):

        creator_ids = Follow.objects.filter(follower=user).values_list(
            "creator_id", flat=True
        )
        return AdminUser.objects.filter(id__in=creator_ids).annotate(
            followers_count=Count("followers")
        )

    def get_latest_followed_episodes(self, user):
        creator_ids = Follow.objects.filter(follower=user).values_list(
            "creator_id", flat=True
        )
        return Episode.objects.filter(
            creator_id__in=creator_ids, status=Episode.Status.PUBLISHED
        ).order_by("-created_at")

    def rate_episode(self, user, episode, score: int, review: str = None):
        rating, created = EpisodeRating.objects.update_or_create(
            episode=episode,
            user=user,
            defaults={"score": score, "review": review},
        )
        return rating, created

    def has_purchased_episode(self, user, episode) -> bool:
        if episode.access_type == Episode.AccessType.FREE:
            return True
        return EpisodePurchase.objects.filter(
            user=user,
            episode=episode,
            status=EpisodePurchase.Status.ACTIVE,
        ).exists()

    def get_purchased_episode_ids(self, user, episode_ids) -> set:
        if not user or not getattr(user, "is_authenticated", False):
            return set()
        if not episode_ids:
            return set()
        return set(
            EpisodePurchase.objects.filter(
                user=user,
                episode_id__in=episode_ids,
                status=EpisodePurchase.Status.ACTIVE,
            ).values_list("episode_id", flat=True)
        )

    def get_published_seasons(self, skillworld=None):
        qs = (
            Season.objects.filter(is_published=True)
            .select_related("creator")
            .annotate(
                episode_count=Count(
                    "episodes",
                    filter=Q(episodes__status=Episode.Status.PUBLISHED),
                    distinct=True,
                )
            )
            .order_by("-created_at")
        )
        if skillworld:
            qs = qs.filter(skillworld=skillworld)
        return qs

    def get_published_seasons_by_creator(self, creator, skillworld=None):
        return self.get_published_seasons(skillworld=skillworld).filter(creator=creator)

    def get_published_episodes_by_creator(self, creator, skillworld=None):
        qs = (
            episodes_for_serializer()
            .filter(
                creator=creator,
                status=Episode.Status.PUBLISHED,
                season__is_published=True,
            )
            .select_related("season")
            .order_by("season__created_at", "order", "created_at")
        )
        if skillworld:
            qs = qs.filter(season__skillworld=skillworld)
        return qs

    def get_verification_stats(self, admin: AdminUser) -> dict:
        now = timezone.now()
        sla_hours = SystemContentConfig.get_config().sla_review_hours
        sla_cutoff = now - timedelta(hours=sla_hours)
        yesterday = now - timedelta(hours=24)

        pending = Episode.objects.filter(status=Episode.Status.REVIEW)
        pending_count = pending.count()

        pending_yesterday = Episode.objects.filter(
            status=Episode.Status.REVIEW,
            submitted_for_review_at__lte=yesterday,
        ).count()

        change_pct = (
            ((pending_count - pending_yesterday) / pending_yesterday) * 100
            if pending_yesterday > 0
            else 0.0
        )

        avg_wait = 0.0
        if pending_count > 0:
            total_wait = sum(
                (now - e.submitted_for_review_at).total_seconds()
                for e in pending.filter(submitted_for_review_at__isnull=False)
            )
            avg_wait = round(total_wait / pending_count, 1)

        reviewed_last_24h = Episode.objects.filter(
            status__in=[
                Episode.Status.PUBLISHED,
                Episode.Status.REJECTED,
                Episode.Status.FLAGGED,
            ],
            updated_at__gte=yesterday,
            submitted_for_review_at__isnull=False,
            reviewed_by=admin,
        )
        avg_response = 0.0
        if reviewed_last_24h.exists():
            total_response = sum(
                (e.updated_at - e.submitted_for_review_at).total_seconds() / 60
                for e in reviewed_last_24h
            )
            avg_response = round(total_response / reviewed_last_24h.count(), 1)

        sla_breach_count = pending.filter(
            submitted_for_review_at__lte=sla_cutoff
        ).count()

        return {
            "pending_count": pending_count,
            "pending_change_pct": round(change_pct, 1),
            "avg_wait_secs": avg_wait,
            "avg_response_time_minutes": avg_response,
            "sla_breach_count": sla_breach_count,
        }

    def get_verification_queue(
        self,
        priority: str = None,
        creator_id: uuid.UUID | str = None,
    ) -> tuple:

        now = timezone.now()
        sla_hours = SystemContentConfig.get_config().sla_review_hours
        sla_cutoff = now - timedelta(hours=sla_hours)

        queryset = (
            Episode.objects.filter(
                status=Episode.Status.REVIEW,
                submitted_for_review_at__isnull=False,
            )
            .select_related("season", "creator")
            .order_by("submitted_for_review_at")
        )

        if creator_id is not None:
            queryset = queryset.filter(creator_id=creator_id)

        if priority == "high":
            threshold = now - timedelta(hours=sla_hours * 0.75)
            queryset = queryset.filter(submitted_for_review_at__lte=threshold)

        elif priority == "medium":
            low_threshold = now - timedelta(hours=sla_hours * 0.50)
            high_threshold = now - timedelta(hours=sla_hours * 0.75)
            queryset = queryset.filter(
                submitted_for_review_at__lte=low_threshold,
                submitted_for_review_at__gt=high_threshold,
            )

        elif priority == "low":
            threshold = now - timedelta(hours=sla_hours * 0.50)
            queryset = queryset.filter(submitted_for_review_at__gt=threshold)

        return queryset, sla_cutoff

    def get_content_approval_stats(self) -> dict:
        today = timezone.localdate()
        today_start = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        )
        today_end = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.max.time())
        )

        pending = Episode.objects.filter(status=Episode.Status.REVIEW).count()

        approved_today = Episode.objects.filter(
            status=Episode.Status.PUBLISHED,
            reviewed_at__gte=today_start,
            reviewed_at__lte=today_end,
        ).count()

        rejected_today = Episode.objects.filter(
            status=Episode.Status.REJECTED,
            reviewed_at__gte=today_start,
            reviewed_at__lte=today_end,
        ).count()

        reviewed_episodes = Episode.objects.filter(
            reviewed_at__isnull=False,
            submitted_for_review_at__isnull=False,
        )

        avg_review_hours = Decimal("0.0")
        if reviewed_episodes.exists():
            durations = reviewed_episodes.annotate(
                review_duration=ExpressionWrapper(
                    F("reviewed_at") - F("submitted_for_review_at"),
                    output_field=DurationField(),
                )
            )

            total_seconds = Decimal("0")
            count = 0
            for episode in durations:
                if episode.review_duration:
                    total_seconds += Decimal(
                        str(episode.review_duration.total_seconds())
                    )
                    count += 1

            if count > 0:
                avg_seconds = total_seconds / Decimal(str(count))
                avg_review_hours = (avg_seconds / Decimal("3600")).quantize(
                    Decimal("0.1")
                )

        return {
            "pending_approval_count": pending,
            "approved_count": approved_today,
            "rejected_count": rejected_today,
            "avg_review_hour": float(avg_review_hours),
        }

    def get_content_approval_list(
        self, status_filter: str = None, skillworld: str = None
    ) -> list:
        episodes = (
            Episode.objects.select_related("creator", "season")
            .prefetch_related(Prefetch("tasks", queryset=EpisodeTask.objects.all()))
            .order_by("-submitted_for_review_at")
        )

        if status_filter == "awaiting_review":
            episodes = episodes.filter(status=Episode.Status.REVIEW)
        elif status_filter == "approved":
            episodes = episodes.filter(status=Episode.Status.PUBLISHED)
        elif status_filter == "rejected":
            episodes = episodes.filter(status=Episode.Status.REJECTED)

        if skillworld:
            episodes = episodes.filter(season__skillworld=skillworld)

        results = []
        for episode in episodes:
            first_task = episode.tasks.first()
            task_type = first_task.kind if first_task else None

            video_duration = "0:00"
            if episode.video_public_id:
                video_duration = getattr(episode, "video_duration", "0:00") or "0:00"

            results.append(
                {
                    "episode_id": str(episode.id),
                    "episode_title": episode.title,
                    "creator_name": (
                        f"{episode.creator.first_name} {episode.creator.last_name}"
                    ).strip()
                    or episode.creator.email,
                    "skillworld": episode.season.skillworld,
                    "season_title": episode.season.title,
                    "status": episode.status,
                    "task_type": task_type or "",
                    "submitted_at": episode.submitted_for_review_at,
                    "video_duration": video_duration,
                }
            )

        return results

    def get_content_distribution(self):
        episode_count = Episode.objects.count()
        project_based_task_count = EpisodeTask.objects.filter(
            kind=EpisodeTask.Kind.PROJECT_BASED
        ).count()
        assessment_based_task_count = EpisodeTask.objects.filter(
            kind=EpisodeTask.Kind.ASSESSMENT
        ).count()

        return {
            "episode_count": episode_count,
            "project_based_task_count": project_based_task_count,
            "assessment_based_task_count": assessment_based_task_count,
        }

    def get_episodes_under_review(self):
        return (
            Episode.objects.select_related("creator", "season")
            .filter(status=Episode.Status.REVIEW)
            .order_by("created_at")
        )

    def get_episode_under_review(self, episode_id: str):
        """Fetch a single episode only if it is currently in REVIEW status."""
        return (
            Episode.objects.select_related("creator")
            .filter(id=episode_id, status=Episode.Status.REVIEW)
            .first()
        )

    def get_watch_history(self, user, completed=None, skillworld=None):
        qs = (
            EpisodeView.objects.filter(user=user)
            .select_related("episode__season", "episode__creator")
            .order_by("-viewed_at")
        )
        if completed is not None:
            qs = qs.filter(completed=completed)
        if skillworld:
            qs = qs.filter(episode__season__skillworld=skillworld)
        return qs

    def delete_watch_history_item(self, user, episode_id: str) -> bool:
        deleted, _ = EpisodeView.objects.filter(
            user=user, episode_id=episode_id
        ).delete()
        return deleted > 0

    def clear_watch_history(self, user) -> int:
        deleted, _ = EpisodeView.objects.filter(user=user).delete()
        return deleted

    def get_saved_episodes(self, user, skillworld=None):
        qs = (
            Episode.objects.filter(
                save_later=user,
                status=Episode.Status.PUBLISHED,
            )
            .select_related("season", "creator")
            .order_by("-updated_at")
        )
        if skillworld:
            qs = qs.filter(season__skillworld=skillworld)
        return qs

    def get_liked_episodes(self, user, skillworld=None):
        qs = (
            Episode.objects.filter(
                liked_by=user,
                status=Episode.Status.PUBLISHED,
            )
            .select_related("season", "creator")
            .order_by("-updated_at")
        )
        if skillworld:
            qs = qs.filter(season__skillworld=skillworld)
        return qs

    def get_user_project_submissions(
        self, user, status=None, skillworld=None, episode_id=None
    ):
        qs = (
            TaskSubmission.objects.filter(user=user)
            .select_related("task__episode__season", "task__episode")
            .order_by("-created_at")
        )
        if status:
            qs = qs.filter(status=status)
        if skillworld:
            qs = qs.filter(task__episode__season__skillworld=skillworld)
        if episode_id:
            qs = qs.filter(task__episode_id=episode_id)
        return qs

    def get_season_by_id(self, season_id: str) -> Optional[Season]:
        try:
            return Season.objects.get(id=season_id)
        except Season.DoesNotExist:
            return None

    def get_episode_by_id(self, episode_id: str) -> Optional[Episode]:
        try:
            return Episode.objects.get(id=episode_id)
        except Episode.DoesNotExist:
            return None
