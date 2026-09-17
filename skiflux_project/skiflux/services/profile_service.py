import logging
from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from skiflux.models import User
from skiflux.models.content import TaskSubmission
from skiflux.models.notification_preference import UserNotificationPreferences
from skiflux.models.app_preference import UserAppPreferences
from skiflux.repositories.content_repository import ContentRepository
from skiflux.repositories.user_repository import UserRepository
from skiflux.services.notification_service import NotificationService
from skiflux.services.wallet_service import WalletService
from django.db import transaction, IntegrityError
from rest_framework.exceptions import ValidationError
from skiflux.utils.media import upload_to_minio
from skiflux.tasks.content import upload_media_from_minio_task

logger = logging.getLogger(__name__)

_DECIMAL_ZERO = Value(
    Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2)
)


class UserProfileService:
    def __init__(self):
        self.content_repo = ContentRepository()
        self.user_repo = UserRepository()
        self.wallet_service = WalletService()
        self.notification_service = NotificationService()

    def get_profile(self, user) -> dict:
        user_data = (
            self.user_repo.get_learner_user_queryset()
            .filter(id=user.id)
            .annotate(
                project_xp=Coalesce(
                    Sum(
                        "task_submissions__cashback_amount",
                        filter=Q(
                            task_submissions__status=TaskSubmission.Status.APPROVED
                        ),
                    ),
                    _DECIMAL_ZERO,
                ),
                assessment_xp=Coalesce(
                    Sum(
                        "assessment_submissions__cashback_amount",
                        filter=Q(assessment_submissions__passed=True),
                    ),
                    _DECIMAL_ZERO,
                ),
            )
            .first()
        )

        total_xp = Decimal("0.00")
        rank = None
        if user_data:
            total_xp = (user_data.project_xp or Decimal("0.00")) + (
                user_data.assessment_xp or Decimal("0.00")
            )
            better_count = User.objects.filter(
                is_staff=False,
                is_superuser=False,
                current_level=user.current_level,
                xp__gt=user.xp,
            ).count()
            tie_count = User.objects.filter(
                is_staff=False,
                is_superuser=False,
                current_level=user.current_level,
                xp=user.xp,
                created_at__lt=user.created_at,
            ).count()
            rank = better_count + tie_count + 1

        wallet = self.wallet_service.get_or_create_wallet(user)

        watch_preview = list(self.content_repo.get_watch_history(user)[:3])

        return {
            "user": user,
            "wallet": wallet,
            "xp": total_xp,
            "tasks_done": user_data.tasks_done if user_data else 0,
            "episodes_completed": user_data.episode_completed_count if user_data else 0,
            "rank": rank,
            "watch_history_preview": watch_preview,
        }

    def update_profile(self, user, data: dict, avatar_file=None) -> User:

        # username uniqueness check
        username = data.get("username")
        if username:
            existing = self.user_repo.get_by_username_exclude(username, user.id)
            if existing:
                raise ValidationError({"username": "This username is already taken."})

        # phone uniqueness check
        phone = data.get("phone")
        if phone:
            existing = self.user_repo.get_by_phone_exclude(phone, user.id)
            if existing:
                raise ValidationError({"phone": "This phone number is already in use."})

        # remove avatar from data dict — handled separately
        data.pop("avatar", None)

        try:
            with transaction.atomic():
                user = self.user_repo.update(user, **data)
        except IntegrityError:
            raise ValidationError({"username": "This username is already taken."})

        # handle avatar upload
        if avatar_file:
            minio_key = upload_to_minio(avatar_file, folder="skiflux_avatars")
            upload_media_from_minio_task.apply_async(
                args=[
                    str(user.id),
                    minio_key,
                    "avatar_url",
                    "User",
                    "image",
                ]
            )

        from skiflux.utils.platform_task_tracker import trigger_platform_task

        trigger_platform_task(user, "complete_profile")

        return user

    def get_leaderboard(
        self,
        current_user,
        search: str = None,
        level: str = None,
    ) -> dict:
        qs = (
            self.user_repo.get_learner_user_queryset()
            .filter(is_active=True)
            .order_by("rank", "created_at")
        )

        if level:
            qs = qs.filter(current_level=level)

        if search:
            from django.db.models import Q

            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(username__icontains=search)
            )

        # always include current user's position even if not in page
        current_user_entry = None
        try:
            current_user_entry = (
                self.user_repo.get_learner_user_queryset()
                .filter(id=current_user.id)
                .first()
            )
        except Exception:
            logger.exception(
                "Failed to fetch current user leaderboard entry",
                extra={"current_user_id": getattr(current_user, "id", None)},
            )

        return {
            "queryset": qs,
            "current_user_entry": current_user_entry,
        }

    def get_watch_history(self, user, completed=None, skillworld=None):
        return self.content_repo.get_watch_history(
            user, completed=completed, skillworld=skillworld
        )

    def delete_watch_history_item(self, user, episode_id: str) -> None:
        if not self.content_repo.delete_watch_history_item(user, episode_id):
            raise ValidationError("Watch history entry not found.")

    def clear_watch_history(self, user) -> int:
        return self.content_repo.clear_watch_history(user)

    def _compute_user_rank(self, user) -> int | None:
        better_count = User.objects.filter(
            is_staff=False,
            is_superuser=False,
            current_level=user.current_level,
            xp__gt=user.xp,
        ).count()
        tie_count = User.objects.filter(
            is_staff=False,
            is_superuser=False,
            current_level=user.current_level,
            xp=user.xp,
            created_at__lt=user.created_at,
        ).count()
        return better_count + tie_count + 1

    def get_public_user_profile(
        self, *, user_id: str = None, username: str = None
    ) -> dict:
        if username:
            user = self.user_repo.get_by_username(username)
        else:
            user = self.user_repo.get_by_id(user_id)

        if (
            not user
            or user.is_staff
            or user.is_superuser
            or not user.is_active
            or user.status in (User.Status.DEACTIVATED, User.Status.SUSPENDED)
        ):
            raise ValidationError("User not found.")

        user_data = (
            self.user_repo.get_learner_user_queryset().filter(id=user.id).first()
        )

        return {
            "user": user,
            "tasks_done": user_data.tasks_done if user_data else 0,
            "episode_completed": user_data.episode_completed_count if user_data else 0,
            "rank": self._compute_user_rank(user),
        }

    def get_saved_episodes(self, user, skillworld=None):
        return self.content_repo.get_saved_episodes(user, skillworld=skillworld)

    def get_liked_episodes(self, user, skillworld=None):
        return self.content_repo.get_liked_episodes(user, skillworld=skillworld)

    def get_user_submissions(
        self, user, status=None, skillworld=None, episode_id=None, offset=0, limit=20
    ):
        project_qs = self.content_repo.get_user_project_submissions(
            user, status, skillworld, episode_id
        )
        assess_qs = self.content_repo.get_user_assessment_submissions(
            user, status, skillworld, episode_id
        )

        if status and status not in ("passed", "failed", "not_passed"):
            assess_qs = assess_qs.none()

        project_list = list(project_qs[:500])
        assess_list = list(assess_qs[:500])

        combined = []
        for sub in project_list:
            ep = sub.task.episode
            combined.append(
                {
                    "id": str(sub.id),
                    "type": "project",
                    "episode_id": str(ep.id),
                    "episode_title": ep.title,
                    "season_title": ep.season.title,
                    "skillworld": ep.season.skillworld,
                    "task_id": str(sub.task.id),
                    "status": sub.status,
                    "submission_text": sub.submission_text or "",
                    "submission_url": sub.submission_url,
                    "submission_file_url": __import__(
                        "skiflux.utils.media",
                        fromlist=["get_submission_file_url"],
                    ).get_submission_file_url(sub),
                    "proof_type": __import__(
                        "skiflux.utils.media",
                        fromlist=["derive_submission_proof_type"],
                    ).derive_submission_proof_type(sub),
                    "cashback_amount": str(sub.cashback_amount),
                    "rejection_reason": sub.rejection_reason,
                    "reviewed_at": sub.reviewed_at,
                    "created_at": sub.created_at,
                    "score_percent": None,
                    "passed": None,
                    "answers": None,
                    "attempt_number": None,
                    "time_taken_seconds": None,
                    "submitted_at": None,
                }
            )

        for sub in assess_list:
            ep = sub.task.episode
            combined.append(
                {
                    "id": str(sub.id),
                    "type": "assessment",
                    "episode_id": str(ep.id),
                    "episode_title": ep.title,
                    "season_title": ep.season.title,
                    "skillworld": ep.season.skillworld,
                    "task_id": str(sub.task.id),
                    "status": "passed" if sub.passed else "failed",
                    "submission_text": None,
                    "submission_url": None,
                    "cashback_amount": str(sub.cashback_amount),
                    "rejection_reason": None,
                    "reviewed_at": None,
                    "created_at": None,
                    "score_percent": sub.score_percent,
                    "passed": sub.passed,
                    "answers": sub.answers,
                    "attempt_number": sub.attempt_number,
                    "time_taken_seconds": sub.time_taken_seconds,
                    "submitted_at": sub.submitted_at,
                }
            )

        combined.sort(
            key=lambda x: x.get("created_at") or x.get("submitted_at") or "",
            reverse=True,
        )

        total = len(combined)
        results = combined[offset : offset + limit]

        return {
            "results": results,
            "total_count": total,
            "offset": offset,
            "limit": limit,
        }

    def register_device(
        self, user, token: str, platform: str = "android", device_id: str = None
    ):
        return self.notification_service.register_device(
            user=user,
            admin_user=None,
            token=token,
            platform=platform,
            device_id=device_id,
        )

    def get_notifications(self, user, unread_only=False, offset=0, limit=20):
        return self.notification_service.get_user_notifications(
            user=user, unread_only=unread_only, offset=offset, limit=limit
        )

    def mark_notification_read(self, user, notification_id: str):
        self.notification_service.mark_notification_read(
            notification_id=notification_id, user=user
        )

    def mark_all_notifications_read(self, user) -> int:
        return self.notification_service.mark_all_notifications_read(user=user)

    def toggle_biometrics(self, user: User) -> dict:
        user.refresh_from_db()  # ensure we have latest state
        user.biometrics_enabled = not user.biometrics_enabled
        user.save(update_fields=["biometrics_enabled"])
        return {"biometrics_enabled": user.biometrics_enabled}

    def get_biometrics_status(self, user: User) -> dict:
        user.refresh_from_db()  # always read fresh from DB
        return {"biometrics_enabled": user.biometrics_enabled}

    def get_notification_preferences(self, user) -> UserNotificationPreferences:
        return UserNotificationPreferences.get_or_create_for_user(user)

    def update_notification_preferences(
        self,
        user,
        data: dict,
    ) -> UserNotificationPreferences:
        prefs = UserNotificationPreferences.get_or_create_for_user(user)
        for field, value in data.items():
            setattr(prefs, field, value)
        prefs.save()
        return prefs

    def get_app_preferences(self, user) -> UserAppPreferences:
        return UserAppPreferences.get_or_create_for_user(user)

    def update_app_preferences(self, user, data: dict) -> UserAppPreferences:
        prefs = UserAppPreferences.get_or_create_for_user(user)
        for field, value in data.items():
            setattr(prefs, field, value)
        prefs.save()
        return prefs
