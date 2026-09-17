import logging
import uuid
from typing import Optional

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from skiflux.models import AdminUser, Episode, Season, User
from skiflux.models.activity import ActivityLog
from skiflux.models.content import (
    EpisodeTask,
    TaskSubmission,
)
from skiflux.models.role import Permission
from skiflux.models.platform_settings import SystemContentConfig
from skiflux.repositories import AdminUserRepository, ContentRepository
from skiflux.tasks.content import upload_media_from_minio_task
from skiflux.services.activity import ActivityService
from skiflux.services.creator_management_service import CreatorManagementService
from skiflux.services.notification_service import NotificationService
from skiflux.utils import (
    bump_upload_attempt,
    generate_otp,
    get_private_avatar_url,
    send_verification_email,
    set_creator_verification_otp,
    verify_creator_email_otp,
)
from skiflux.utils.media import (
    creator_display_name,
    delete_from_cloudinary,
    send_content_upload_received_email,
    upload_to_minio,
)

logger = logging.getLogger(__name__)


REUPLOAD_ALLOWED_STATUSES = frozenset(
    {
        Episode.Status.DRAFT,
        Episode.Status.PROCESSING,
        Episode.Status.REJECTED,
        Episode.Status.FAILED,
        Episode.Status.REVIEW,
    }
)


class ContentAccessService:
    def can_user_access_episode(self, user: User, episode: Episode) -> bool:
        if isinstance(user, AdminUser):
            if user.role_type == AdminUser.RoleType.SUPER_ADMIN:
                return True
            if episode.creator_id == user.id and user.can_use_studio:
                return True
            return False
        if episode.access_type == Episode.AccessType.FREE:
            return True

        return ContentRepository().has_purchased_episode(user, episode)


class StudioService:
    def __init__(self):
        self.admin_repo = AdminUserRepository()
        self.content_repo = ContentRepository()
        self.creator_management_service = CreatorManagementService()
        self.notification_service = NotificationService()

    def _queue_season_thumbnail_upload(
        self, season_id: str, minio_object_key: str
    ) -> None:

        transaction.on_commit(
            lambda key=minio_object_key: upload_media_from_minio_task.delay(
                instance_id=season_id,
                minio_object_key=key,
                model_name="Season",
                field_name="cover_image_public_id",
                resource_type="image",
            )
        )

    @transaction.atomic
    def update_season_thumbnail(
        self,
        admin: AdminUser,
        season_id: str,
        cover_image_file,
    ) -> Season:
        """
        Update only the cover image for a season.
        """
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError({"season_id": "Season not found."})

        # Check permission: creator or admin with CONTENT_MANAGE
        if season.creator_id != admin.id and not admin.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied(
                "You don't have permission to update this season's cover image."
            )

        # Delete old cover if exists
        if season.cover_image_public_id:
            try:
                delete_from_cloudinary(season.cover_image_public_id)
            except Exception as e:
                logger.warning(f"Failed to delete old cover from Cloudinary: {e}")

        # Upload new cover
        minio_object_key = upload_to_minio(
            cover_image_file, folder="skiflux_season_covers"
        )
        self._queue_season_thumbnail_upload(str(season.id), minio_object_key)

        return season

    def verify_email(self, email: str, otp: str):
        if not verify_creator_email_otp(email, otp):
            raise ValidationError({"otp": "Invalid or expired OTP."})

        admin = self.admin_repo.get_by_email(email)
        if not admin:
            raise ValidationError({"email": "Creator account not found."})

        if admin.is_verified:
            raise ValidationError({"email": "Email is already verified."})

        admin.is_verified = True
        admin.is_active = True
        admin.add_role_type(AdminUser.RoleType.CREATOR)
        admin.save(
            update_fields=["is_verified", "is_active", "role_types", "updated_at"]
        )
        return admin

    def resend_otp(self, email: str):
        content_creator = self.admin_repo.get_by_email(email)
        if not content_creator:
            raise ValidationError("No account found with this email address.")

        if content_creator.is_verified:
            raise ValidationError("Email is already verified.")
        otp = generate_otp()
        set_creator_verification_otp(content_creator.email, otp)
        send_verification_email(content_creator.email, otp)

    @transaction.atomic
    def attach_tasks(
        self,
        admin: AdminUser,
        episode_id: str,
        project_task_data: dict | None = None,
        assessment_task_data: dict | None = None,
    ):
        episode = self.content_repo.get_episode(episode_id, creator=admin)
        if not episode:
            raise ValidationError("Episode not found or you do not own it.")
        if episode.status == Episode.Status.PUBLISHED:
            raise ValidationError(
                "Cannot attach or update tasks on a published episode."
            )

        result = {"project_task": None, "assessment_task": None}

        if project_task_data:
            existing = self.content_repo.get_task_by_kind(
                episode, EpisodeTask.Kind.PROJECT_BASED
            )
            if existing:
                raise ValidationError("Episode already has a project task.")
            pt = self.content_repo.create_task(
                episode=episode,
                kind=EpisodeTask.Kind.PROJECT_BASED,
                sla_time_limit_hours=project_task_data.get("sla_time_limit_hours", 24),
                task_brief=project_task_data.get("task_brief"),
                accepted_proof_types=project_task_data.get("accepted_proof_types"),
                completion_criteria=project_task_data.get("completion_criteria"),
            )
            result["project_task"] = pt

        if assessment_task_data:
            existing = self.content_repo.get_task_by_kind(
                episode, EpisodeTask.Kind.ASSESSMENT
            )
            if existing:
                raise ValidationError("Episode already has an assessment task.")

            questions_data = assessment_task_data.pop("questions", [])
            at = self.content_repo.create_task(
                episode=episode,
                kind=EpisodeTask.Kind.ASSESSMENT,
                sla_time_limit_hours=assessment_task_data.get(
                    "sla_time_limit_hours", 24
                ),
                pass_score_percent=assessment_task_data.get("pass_score_percent"),
                time_limit_minutes=assessment_task_data.get("time_limit_minutes"),
                max_attempts=assessment_task_data.get("max_attempts"),
            )
            if questions_data:
                self.content_repo.replace_assessment_questions(
                    at,
                    questions_data,
                )
            result["assessment_task"] = at

        return result

    @transaction.atomic
    def update_tasks(
        self,
        admin: AdminUser,
        episode_id: str,
        project_task_data: dict | None = None,
        assessment_task_data: dict | None = None,
    ):
        episode = self.content_repo.get_episode(episode_id, creator=admin)
        if not episode:
            raise ValidationError("Episode not found or you do not own it.")
        if episode.status == Episode.Status.PUBLISHED:
            raise ValidationError(
                "Cannot attach or update tasks on a published episode."
            )

        result = {"project_task": None, "assessment_task": None}

        if project_task_data:
            pt = self.content_repo.get_task_by_kind(
                episode, EpisodeTask.Kind.PROJECT_BASED
            )
            if not pt:
                raise ValidationError("Project task not found for this episode.")
            pt = self.content_repo.update_task(pt, **project_task_data)
            result["project_task"] = pt

        if assessment_task_data:
            at = self.content_repo.get_task_by_kind(
                episode, EpisodeTask.Kind.ASSESSMENT
            )
            if not at:
                raise ValidationError("Assessment task not found for this episode.")

            questions_data = assessment_task_data.pop("questions", None)
            at = self.content_repo.update_task(at, **assessment_task_data)
            if questions_data is not None:
                self.content_repo.replace_assessment_questions(at, questions_data)
            result["assessment_task"] = at

        return result

    @transaction.atomic
    def register_creator(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        username: str,
    ):
        if self.admin_repo.get_by_email(email):
            raise ValidationError("Email already registered.")

        if self.admin_repo.get_by_username(username):
            raise ValidationError("This username is already taken.")

        admin = self.admin_repo.create(
            email=email,
            first_name=first_name,
            last_name=last_name,
            username=username,
            password=password,
            role_type=AdminUser.RoleType.CREATOR,
            role_types=[AdminUser.RoleType.CREATOR],
            is_active=False,
        )
        otp_code = generate_otp()
        set_creator_verification_otp(email, otp_code)
        send_verification_email(email, otp_code)
        self.creator_management_service.invalidate_directory_stats_cache()
        return admin

    @transaction.atomic
    def create_season(
        self,
        admin: AdminUser,
        title: str,
        description: str,
        skillworld: str,
        cover_image_file=None,
    ) -> Season:

        # validate the amount of season per creator from system content config
        config = SystemContentConfig.get_config()
        max_seasons = config.max_seasons_per_creator
        current_seasons = self.content_repo.get_creator_season_count(admin)

        if current_seasons >= max_seasons:
            raise ValidationError(
                f"You are not allowed to create more than {max_seasons} seasons."
            )

        season = self.content_repo.create_season(
            creator=admin,
            title=title,
            description=description,
            skillworld=skillworld,
        )

        # Upload thumbnail if provided
        if cover_image_file:
            minio_object_key = upload_to_minio(
                cover_image_file, folder="skiflux_season_covers"
            )
            self._queue_season_thumbnail_upload(str(season.id), minio_object_key)

        return season

    def list_my_seasons(self, admin: AdminUser):
        seasons = self.content_repo.get_seasons_by_creator(admin)
        result = []
        for season in seasons:
            sla_avg = self.content_repo.get_sla_avg_for_season(season)
            result.append(
                {
                    "id": str(season.id),
                    "title": season.title,
                    "description": season.description,
                    "skillworld": season.skillworld,
                    "is_published": season.is_published,
                    "price": season.price,
                    "cover_image_url": get_private_avatar_url(
                        season.cover_image_public_id
                    ),
                    "episodes_count": season.episodes_count,
                    "submission_count": season.submission_count,
                    "sla_avg": sla_avg,
                    "created_at": season.created_at,
                }
            )
        return result

    def _queue_episode_thumbnail_upload(
        self, episode_id: str, minio_object_key: str
    ) -> None:
        transaction.on_commit(
            lambda key=minio_object_key: upload_media_from_minio_task.delay(
                instance_id=episode_id,
                minio_object_key=key,
                model_name="Episode",
                field_name="thumbnail_public_id",
                resource_type="image",
            )
        )

    def _send_video_received_email_and_queue_upload(
        self,
        episode_id: str,
        minio_object_key: str,
        title: str,
        admin: AdminUser,
        review_mode: bool = False,
    ) -> None:
        bump_upload_attempt(episode_id)

        def _send_and_queue():
            send_content_upload_received_email(
                email=admin.email,
                episode_name=title,
                creator_name=creator_display_name(admin),
                episode_id=episode_id,
            )
            upload_media_from_minio_task.delay(
                instance_id=episode_id,
                minio_object_key=minio_object_key,
                model_name="Episode",
                field_name="video_public_id",
                resource_type="video",
                review_mode=review_mode,
            )

        transaction.on_commit(_send_and_queue)

    @transaction.atomic
    def create_episode(
        self,
        admin: AdminUser,
        season_id: str,
        title: str,
        description: str,
        order: int,
        access_type: str = "paid",
        video_file=None,
        thumbnail_file=None,
    ):
        season = self.content_repo.get_season(season_id, creator=admin)
        if not season:
            raise ValidationError("Season not found or you do not own it.")

        # validate the amount of episodes per season from system content config
        config = SystemContentConfig.get_config()
        max_episodes_per_season = config.max_episodes_per_season

        episode_count = self.content_repo.get_episode_count_by_season(season)

        if episode_count >= max_episodes_per_season:
            raise ValidationError(
                f"You are not allowed to create more than {max_episodes_per_season} episodes in a season."  # noqa: E501
            )

        episode = self.content_repo.create_episode(
            creator=admin,
            season=season,
            title=title,
            description=description,
            order=order,
            access_type=access_type,
        )
        episode_id = str(episode.id)
        if video_file:
            minio_object_key = upload_to_minio(video_file, folder="skiflux_episodes")
            self._send_video_received_email_and_queue_upload(
                episode_id, minio_object_key, title, admin
            )
        if thumbnail_file:
            minio_object_key = upload_to_minio(
                thumbnail_file, folder="skiflux_thumbnails"
            )
            self._queue_episode_thumbnail_upload(episode_id, minio_object_key)
        return episode

    @transaction.atomic
    def create_episode_for_review(
        self,
        admin: AdminUser,
        season_id: str,
        title: str,
        description: str,
        order: Optional[int] = None,
        access_type: str = "paid",
        video_file=None,
        thumbnail_file=None,
    ):
        season = self.content_repo.get_season(season_id, creator=admin)
        if not season:
            raise ValidationError("Season not found or you do not own it.")
        episode = self.content_repo.create_episode(
            creator=admin,
            season=season,
            title=title,
            description=description,
            order=order,
            access_type=access_type,
            submitted_for_review=True,
        )
        episode_id = str(episode.id)
        if video_file:
            minio_object_key = upload_to_minio(video_file, folder="skiflux_episodes")
            self._send_video_received_email_and_queue_upload(
                episode_id, minio_object_key, title, admin, review_mode=True
            )
        if thumbnail_file:
            minio_object_key = upload_to_minio(
                thumbnail_file, folder="skiflux_thumbnails"
            )
            self._queue_episode_thumbnail_upload(episode_id, minio_object_key)
        return episode

    @transaction.atomic
    def reupload_episode_video(
        self,
        admin: AdminUser,
        episode_id: str,
        video_file,
        thumbnail_file=None,
    ) -> Episode:
        episode = self.content_repo.get_episode(episode_id, creator=admin)
        if not episode:
            raise ValidationError("Episode not found or you do not own it.")
        if episode.status not in REUPLOAD_ALLOWED_STATUSES:
            raise ValidationError(
                "Cannot replace video while this episode is published. "
                "Contact support if you need to update live content."
            )
        old_public_id = episode.video_public_id
        original_status = episode.status
        episode.status = Episode.Status.PROCESSING
        episode.video_public_id = None
        episode.save(update_fields=["status", "video_public_id", "updated_at"])

        if old_public_id:
            from skiflux.tasks.content import cleanup_cloudinary_asset_task

            cleanup_cloudinary_asset_task.delay(old_public_id, resource_type="video")

        episode_id_str = str(episode.id)
        if video_file:
            minio_object_key = upload_to_minio(video_file, folder="skiflux_episodes")
            # Preserve review mode if episode was originally under review
            review_mode = original_status == Episode.Status.REVIEW
            self._send_video_received_email_and_queue_upload(
                episode_id_str,
                minio_object_key,
                episode.title,
                admin,
                review_mode=review_mode,
            )

        if thumbnail_file:
            minio_object_key = upload_to_minio(
                thumbnail_file, folder="skiflux_thumbnails"
            )
            self._queue_episode_thumbnail_upload(episode_id_str, minio_object_key)
        return episode

    def list_my_episodes(self, admin: AdminUser):
        return self.content_repo.get_episodes_by_creator(admin)

    def submit_episode_for_review(self, admin: AdminUser, episode_id: str):
        episode = self.content_repo.get_episode(episode_id, creator=admin)
        if not episode:
            raise ValidationError("Episode not found or you do not own it.")

        if episode.status not in (Episode.Status.DRAFT, Episode.Status.REJECTED):
            raise ValidationError(
                "Only draft or rejected episodes can be submitted for review."
            )

        if not episode.video_public_id:
            raise ValidationError(
                "Episode must have a video uploaded before submitting for review."
            )

        episode.status = Episode.Status.REVIEW
        episode.submitted_for_review_at = timezone.now()
        episode.save(update_fields=["status", "submitted_for_review_at", "updated_at"])
        return episode

    @transaction.atomic
    def update_creator_profile(
        self,
        admin: AdminUser,
        first_name: str = None,
        last_name: str = None,
        username: str = None,
        display_name: str = None,
        bio: str = None,
        avatar_file=None,
    ) -> AdminUser:
        update_fields = []

        if first_name is not None:
            admin.first_name = first_name
            update_fields.append("first_name")

        if last_name is not None:
            admin.last_name = last_name
            update_fields.append("last_name")

        if username is not None:
            existing = self.admin_repo.get_by_username(username)
            if existing and existing.id != admin.id:
                raise ValidationError("This username is already taken.")
            admin.username = username
            update_fields.append("username")

        if bio is not None:
            admin.bio = bio
            update_fields.append("bio")

        if display_name is not None:
            admin.display_name = display_name
            update_fields.append("display_name")

        if update_fields:
            update_fields.append("updated_at")
            admin.save(update_fields=update_fields)

        if avatar_file:
            minio_object_key = upload_to_minio(avatar_file, folder="skiflux_avatars")
            transaction.on_commit(
                lambda key=minio_object_key: upload_media_from_minio_task.delay(
                    instance_id=str(admin.id),
                    minio_object_key=key,
                    model_name="AdminUser",
                    field_name="avatar_public_id",
                    resource_type="image",
                )
            )

        return admin

    def get_my_profile(self, admin: AdminUser) -> dict:
        """Get the current creator's profile with stats."""
        seasons = self.content_repo.get_seasons_by_creator(admin)
        episodes = self.content_repo.get_episodes_by_creator(admin)

        tasks = self.content_repo.get_tasks_for_episodes(episodes)
        task_submissions_count = self.content_repo.get_task_submissions_count(tasks)
        assessment_submissions_count = (
            self.content_repo.get_assessment_submissions_count(tasks)
        )
        total_submissions = task_submissions_count + assessment_submissions_count

        return {
            "id": str(admin.id),
            "email": admin.email,
            "username": admin.username,
            "first_name": admin.first_name,
            "last_name": admin.last_name,
            "bio": admin.bio,
            "display_name": admin.display_name,
            "avatar_url": get_private_avatar_url(admin.avatar_public_id),
            "role_type": admin.role_type,
            "is_active": admin.is_active,
            "is_verified": admin.is_verified,
            "created_at": admin.created_at,
            "updated_at": admin.updated_at,
            "stats": {
                "seasons_count": seasons.count(),
                "episodes_count": episodes.count(),
                "submissions_count": total_submissions,
                "subscribers_count": admin.followers.count(),
            },
        }

    def get_my_stats(self, admin: AdminUser) -> dict:
        """Get the current creator's analytics."""
        return self.creator_management_service.get_creator_analytics(str(admin.id))

    def get_episode_full_details(self, admin: AdminUser, episode_id: str) -> dict:
        """Return episode, tasks, submissions and comments for the episode.

        Accessible if `admin` is the episode owner (creator) or has
        Permission.CONTENT_VIEW.
        """
        try:
            uuid.UUID(episode_id)  # validate format first
        except (ValueError, AttributeError):
            raise ValidationError("Invalid episode ID format.")

        episode = self.content_repo.get_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")

        # owner can access
        is_owner = isinstance(admin, AdminUser) and episode.creator_id == admin.id

        # admin with permission can access
        has_content_view = False
        if isinstance(admin, AdminUser):
            try:
                has_content_view = admin.has_permission(Permission.CONTENT_VIEW)
            except Exception:
                has_content_view = False

        if not (is_owner or has_content_view):
            raise PermissionDenied("You do not have permission to view this episode.")

        tasks = episode.tasks.all()

        task_submissions = self.content_repo.get_task_submissions_by_episode(episode)
        assessment_submissions = (
            self.content_repo.get_assessment_submissions_by_episode(episode)
        )

        comments = self.content_repo.get_comments(episode)

        return {
            "episode": episode,
            "tasks": tasks,
            "task_submissions": task_submissions,
            "assessment_submissions": assessment_submissions,
            "comments": comments,
        }

    def get_episode_stats(self, admin: AdminUser, episode_id: str) -> dict:
        """Return task-related stats for an episode.

        Accessible if `admin` is the episode owner (creator) or has
        Permission.CONTENT_VIEW.
        Returns: total_views, total_submissions, completion_rate, pending_review_count
        """
        try:
            uuid.UUID(episode_id)
        except (ValueError, AttributeError):
            raise ValidationError("Invalid episode ID format.")

        episode = self.content_repo.get_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")

        # owner can access
        is_owner = isinstance(admin, AdminUser) and episode.creator_id == admin.id

        # admin with permission can access
        has_content_view = False
        if isinstance(admin, AdminUser):
            try:
                has_content_view = admin.has_permission(Permission.CONTENT_VIEW)
            except Exception:
                has_content_view = False

        if not (is_owner or has_content_view):
            raise PermissionDenied("You do not have permission to view this episode.")

        # total views
        total_views = self.content_repo.get_episode_total_view(episode)

        # total submissions (project + assessment)
        task_submissions_count = (
            self.content_repo.get_task_submissions_count_by_episode(episode)
        )
        assessment_submissions_count = (
            self.content_repo.get_assessment_submissions_count_by_episode(episode)
        )
        total_submissions = task_submissions_count + assessment_submissions_count

        # completion rate: percent of views marked completed
        completed_views = episode.views.filter(completed=True).count()
        completion_rate = (
            round((completed_views / total_views) * 100, 1) if total_views else 0.0
        )

        # pending review count (only project-based submissions are reviewed)
        pending_review_count = (
            self.content_repo.get_pending_task_submissions_count_by_episode(episode)
        )

        return {
            "total_views": total_views,
            "total_submissions": total_submissions,
            "completion_rate": completion_rate,
            "pending_review_count": pending_review_count,
        }

    def _check_episode_access(self, admin: AdminUser, episode_id: str) -> Episode:
        """
        Check access and return episode. Raises ValidationError or PermissionDenied.
        """
        try:
            uuid.UUID(episode_id)
        except (ValueError, AttributeError):
            raise ValidationError("Invalid episode ID format.")

        episode = self.content_repo.get_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")

        # owner can access
        is_owner = isinstance(admin, AdminUser) and episode.creator_id == admin.id

        # admin with permission can access
        has_content_view = False
        if isinstance(admin, AdminUser):
            try:
                has_content_view = admin.has_permission(Permission.CONTENT_VIEW)
            except Exception:
                has_content_view = False

        if not (is_owner or has_content_view):
            raise PermissionDenied("You do not have permission to view this episode.")

        return episode

    def get_episode_task(self, admin: AdminUser, episode_id: str, task_id: str) -> dict:
        """Get task details with submission counts."""
        episode = self._check_episode_access(admin, episode_id)

        task = self.content_repo.get_task_by_id_and_episode(task_id, episode)
        if not task:
            raise ValidationError("Task not found for this episode.")

        # count submissions
        if task.kind == EpisodeTask.Kind.PROJECT_BASED:
            total_submissions = task.submissions.count()
            pending_submissions = task.submissions.filter(
                status=TaskSubmission.Status.PENDING
            ).count()
        else:  # ASSESSMENT
            total_submissions = task.assessment_submissions.count()
            pending_submissions = 0  # assessments are auto-graded

        result = {
            "id": str(task.id),
            "episode_id": str(episode.id),
            "kind": task.kind,
            "sla_time_limit_hours": task.sla_time_limit_hours,
            "task_brief": task.task_brief,
            "accepted_proof_types": task.accepted_proof_types,
            "pass_score_percent": task.pass_score_percent,
            "time_limit_minutes": task.time_limit_minutes,
            "max_attempts": task.max_attempts,
            "completion_criteria": task.completion_criteria,
            "total_submissions": total_submissions,
            "pending_submissions": pending_submissions,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
        if task.kind == EpisodeTask.Kind.ASSESSMENT:
            result["questions"] = [
                {
                    "id": str(q.id),
                    "order": q.order,
                    "question_text": q.question_text,
                    "option_a": q.option_a,
                    "option_b": q.option_b,
                    "option_c": q.option_c,
                    "option_d": q.option_d,
                    "correct_answer": q.correct_answer,
                }
                for q in task.questions.all().order_by("order")
            ]
        return result

    def _sla_status_for_submission(
        self,
        sub: TaskSubmission,
        *,
        now=None,
        sla_window=None,
    ):
        if sub.status == TaskSubmission.Status.PENDING:
            now = now or timezone.now()
            if sla_window is None:
                sla_hours = SystemContentConfig.get_config().sla_review_hours
                sla_window = timezone.timedelta(hours=sla_hours)
            time_elapsed = now - sub.created_at
            if time_elapsed > sla_window:
                return "breached"
            remaining = sla_window - time_elapsed
            return remaining.total_seconds()
        if sub.status in [
            TaskSubmission.Status.APPROVED,
            TaskSubmission.Status.REJECTED,
        ]:
            return "done"
        return None

    def serialize_task_submission(
        self,
        sub: TaskSubmission,
        *,
        now=None,
        sla_window=None,
    ) -> dict:
        from skiflux.utils.media import (
            derive_submission_proof_type,
            get_submission_file_url,
        )

        return {
            "id": str(sub.id),
            "user_id": str(sub.user.id),
            "user_email": sub.user.email,
            "user_name": f"{sub.user.first_name} {sub.user.last_name}".strip(),
            "user_avatar_url": sub.user.avatar_url,
            "submission_text": sub.submission_text,
            "submission_url": sub.submission_url,
            "submission_file_url": get_submission_file_url(sub),
            "proof_type": derive_submission_proof_type(sub),
            "status": sub.status,
            "sla": self._sla_status_for_submission(sub, now=now, sla_window=sla_window),
            "reviewed_by": (
                f"{sub.reviewed_by.first_name} {sub.reviewed_by.last_name}"
            ).strip()
            if sub.reviewed_by
            else None,
            "reviewed_at": sub.reviewed_at,
            "created_at": sub.created_at,
            "cashback_amount": str(sub.cashback_amount),
            "rejection_reason": sub.rejection_reason,
            "feedback": sub.feedback,
        }

    def serialize_task_submissions(self, submissions) -> list[dict]:
        now = timezone.now()
        sla_hours = SystemContentConfig.get_config().sla_review_hours
        sla_window = timezone.timedelta(hours=sla_hours)
        return [
            self.serialize_task_submission(sub, now=now, sla_window=sla_window)
            for sub in submissions
        ]

    def get_task_submissions_queryset(
        self,
        admin: AdminUser,
        episode_id: str,
        task_id: str,
        status_filter: str = None,
    ):
        """Return queryset of task submissions for pagination in the view layer."""
        episode = self._check_episode_access(admin, episode_id)

        task = self.content_repo.get_task_by_id_and_episode(task_id, episode)
        if not task:
            raise ValidationError("Task not found for this episode.")

        if task.kind != EpisodeTask.Kind.PROJECT_BASED:
            raise ValidationError(
                "Only project-based tasks have submissions. "
                "Assessment submissions use a different endpoint."
            )

        qs = self.content_repo.get_task_submissions_by_task(task)

        if status_filter:
            valid_statuses = [s[0] for s in TaskSubmission.Status.choices]
            if status_filter not in valid_statuses:
                raise ValidationError(
                    f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )
            qs = qs.filter(status=status_filter)

        return qs

    def get_pending_task_submissions_queryset(self, creator_id: str):
        """Return queryset of pending task submissions for a creator."""
        creator = self.content_repo.get_creator_by_id(creator_id)
        if not creator:
            raise ValidationError("Creator not found.")

        return self.content_repo.get_pending_task_submissions_for_creator(creator)

    def reject_task_submission(
        self,
        admin: AdminUser,
        episode_id: str,
        task_id: str,
        submission_id: str,
        rejection_reason: str,
    ):
        episode = self._check_episode_access(admin, episode_id)

        task = self.content_repo.get_task_by_id_and_episode(task_id, episode)
        if not task or task.kind != EpisodeTask.Kind.PROJECT_BASED:
            raise ValidationError("Project task not found for this episode.")

        sub = self.content_repo.get_task_submission(submission_id, task)
        if not sub:
            raise ValidationError("Submission not found.")

        if sub.status != TaskSubmission.Status.PENDING:
            raise ValidationError("Only pending submissions can be rejected.")

        if not rejection_reason or not rejection_reason.strip():
            raise ValidationError(
                {"rejection_reason": "A rejection reason is required."}
            )

        self.content_repo.mark_submission_rejected(sub, admin, rejection_reason.strip())

        try:
            ActivityService.log_activity(
                action_type=ActivityLog.ActionType.CONTENT_REJECTED,
                description=(
                    f"Task submission by {sub.user.email} was rejected for {episode.title}."  # noqa: E501
                ),
                actor=admin,
                subject=sub.user,
                metadata={
                    "submission_id": str(sub.id),
                    "episode_id": str(episode.id),
                    "reason": rejection_reason.strip()[:200],
                },
            )
        except Exception:
            pass  # non-fatal

        # Notify the submitting learner (creator-owned reject path)
        try:
            NotificationService().send_push_for_event(
                user=sub.user,
                event_type="task_rejected_with_feedback",
                title="Task Needs Revision",
                body=f"Your submission for '{episode.title}' was rejected by the creator.  {rejection_reason.strip()[:100]}",  # noqa: E501
                data={
                    "type": "task_rejected",
                    "episode_id": str(episode.id),
                    "submission_id": str(sub.id),
                },
            )
        except Exception:
            logger.warning("Push notify (creator reject) failed (non-fatal)")

        return sub

    def get_episode_comments(
        self,
        admin: AdminUser,
        episode_id: str,
        flagged: bool = False,
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """Get paginated episode comments, optionally filtered by flagged status."""
        episode = self._check_episode_access(admin, episode_id)

        # Get comments
        qs = self.content_repo.get_paginated_comments(episode, flagged)

        total_count = qs.count()

        # paginate
        comments = qs[offset : offset + limit]

        results = []
        for comment in comments:
            results.append(
                {
                    "id": str(comment.id),
                    "user_id": str(comment.user.id),
                    "user_email": comment.user.email,
                    "user_name": (
                        f"{comment.user.first_name} {comment.user.last_name}"
                    ).strip(),
                    "user_avatar_url": comment.user.avatar_url,
                    "text": comment.text,
                    "created_at": comment.created_at,
                    "audio_public_id": comment.audio_public_id,
                    "audio_url": (
                        __import__(
                            "skiflux.utils.media", fromlist=["get_private_media_url"]
                        ).get_private_media_url(
                            comment.audio_public_id, resource_type="video"
                        )
                        if comment.audio_public_id
                        else None
                    ),
                }
            )

        return {
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "results": results,
        }

    def register_device(
        self,
        admin_user: AdminUser,
        token: str,
        platform: str = "android",
        device_id: str = None,
    ):
        """Creator/admin registers a device token. Delegates to NotificationService."""
        if not isinstance(admin_user, AdminUser):
            raise ValidationError("Admin/creator context required.")
        return self.notification_service.register_device(
            user=None,
            admin_user=admin_user,
            token=token,
            platform=platform,
            device_id=device_id,
        )

    def get_notifications(
        self, admin_user: AdminUser, unread_only=False, offset=0, limit=20
    ):
        """Creator's persisted notifications (for web portal bell/history)."""
        if not isinstance(admin_user, AdminUser):
            raise ValidationError("Admin/creator context required.")
        return self.notification_service.get_admin_notifications(
            admin_user=admin_user, unread_only=unread_only, offset=offset, limit=limit
        )

    def mark_notification_read(self, admin_user: AdminUser, notification_id: str):
        """Mark one of the creator's notifications read."""
        if not isinstance(admin_user, AdminUser):
            raise ValidationError("Admin/creator context required.")
        self.notification_service.mark_notification_read(
            notification_id=notification_id, admin_user=admin_user
        )

    def update_season(
        self,
        admin: AdminUser,
        season_id: str,
        title: str = None,
        description: str = None,
        skillworld: str = None,
        price: str = None,
        cover_image_file=None,
    ) -> Season:
        """
        Update a season. Creator or admin with CONTENT_MANAGE permission can update.
        """
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError({"season_id": "Season not found."})

        # Check permission: creator or admin with CONTENT_MANAGE
        if season.creator_id != admin.id and not admin.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied("You don't have permission to update this season.")

        # Update fields
        if title is not None:
            season.title = title
        if description is not None:
            season.description = description
        if skillworld is not None:
            season.skillworld = skillworld
        if price is not None:
            season.price = price

        # Handle cover image if provided
        if cover_image_file:
            if season.cover_image_public_id:
                try:
                    delete_from_cloudinary(season.cover_image_public_id)
                except Exception as e:
                    logger.warning(f"Failed to delete old cover from Cloudinary: {e}")

            # Upload new cover
            minio_object_key = upload_to_minio(
                cover_image_file, folder="skiflux_season_covers"
            )
            self._queue_season_thumbnail_upload(str(season.id), minio_object_key)
        season.updated_at = timezone.now()
        season.save()

        display_name = creator_display_name(admin)

        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.SEASON_UPDATED,
            description=(
                f"Season '{season.title}' was updated by {display_name}."  # noqa: E501
            ),
            actor=admin,
            subject=season,
            metadata={
                "season_id": str(season.id),
                "updated_fields": [
                    f
                    for f in ["title", "description", "skillworld", "price"]
                    if locals().get(f) is not None
                ],
            },
        )

        return season

    def unpublish_season(self, admin: AdminUser, season_id: str) -> Season:
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError({"season_id": "Season not found."})

        # Check permission: creator or admin with CONTENT_MANAGE
        if season.creator_id != admin.id and not admin.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied(
                "You don't have permission to unpublish this season."
            )

        if not season.is_published:
            raise ValidationError({"season": "Season is already unpublished."})

        season.is_published = False
        season.updated_at = timezone.now()
        season.save(update_fields=["is_published", "updated_at"])

        display_name = creator_display_name(admin)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.SEASON_UNPUBLISHED,
            description=(
                f"Season '{season.title}' was unpublished by {display_name}."  # noqa: E501
            ),
            actor=admin,
            subject=season,
            metadata={"season_id": str(season.id), "title": season.title},
        )

        return season

    def remove_season(self, admin: AdminUser, season_id: str) -> None:
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError({"season_id": "Season not found."})

        # Check permission: creator or admin with CONTENT_MANAGE
        if season.creator_id != admin.id and not admin.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied("You don't have permission to remove this season.")

        season_id_str = str(season.id)
        season_title = season.title

        # Delete the season (cascade will handle episodes)
        season.delete()

        display_name = creator_display_name(admin)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.SEASON_REMOVED,
            description=(
                f"Season '{season_title}' was removed by {display_name}."  # noqa: E501
            ),
            actor=admin,
            metadata={"season_id": season_id_str, "title": season_title},
        )

    def update_episode(
        self,
        admin: AdminUser,
        episode_id: str,
        title: str = None,
        description: str = None,
        order: int = None,
        access_type: str = None,
        thumbnail_file=None,
    ) -> Episode:
        """
        Update an episode. Creator or admin with CONTENT_MANAGE permission can update.
        """
        episode = self.content_repo.get_episode_by_id(episode_id)
        if not episode:
            raise ValidationError({"episode_id": "Episode not found."})

        # Check permission: creator or admin with CONTENT_MANAGE
        if episode.creator_id != admin.id and not admin.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied("You don't have permission to update this episode.")

        # Cannot update status or video while processing
        if episode.status == Episode.Status.PROCESSING:
            raise ValidationError(
                {"episode": "Cannot update episode while it's being processed."}
            )

        # Update fields
        if title is not None:
            episode.title = title
        if description is not None:
            episode.description = description
        if order is not None:
            episode.order = order
        if access_type is not None:
            episode.access_type = access_type
        if thumbnail_file:
            if episode.thumbnail_public_id:
                try:
                    delete_from_cloudinary(episode.thumbnail_public_id)
                except Exception as e:
                    logger.warning(f"Failed to delete thumbnail from Cloudinary: {e}")
            minio_object_key = upload_to_minio(
                thumbnail_file, folder="skiflux_episode_thumbnails"
            )
            self._queue_episode_thumbnail_upload(str(episode.id), minio_object_key)
        episode.updated_at = timezone.now()
        episode.save(
            update_fields=[
                "title",
                "description",
                "order",
                "access_type",
                "thumbnail_public_id",
                "updated_at",
            ]
        )

        display_name = creator_display_name(admin)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.EPISODE_UPDATED,
            description=(
                f"Episode '{episode.title}' was updated by {display_name}."  # noqa: E501
            ),
            actor=admin,
            subject=episode,
            metadata={
                "episode_id": str(episode.id),
                "updated_fields": [
                    f
                    for f in ["title", "description", "order", "access_type"]
                    if locals().get(f) is not None
                ],
            },
        )

        return episode

    def unpublish_episode(self, admin: AdminUser, episode_id: str) -> Episode:
        episode = self.content_repo.get_episode_by_id(episode_id)
        if not episode:
            raise ValidationError({"episode_id": "Episode not found."})

        # Check permission: creator or admin with CONTENT_MANAGE
        if episode.creator_id != admin.id and not admin.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied(
                "You don't have permission to unpublish this episode."
            )

        if episode.status != Episode.Status.PUBLISHED:
            raise ValidationError(
                {"episode": "Only published episodes can be unpublished."}
            )

        episode.status = Episode.Status.DRAFT
        episode.updated_at = timezone.now()
        episode.save(update_fields=["status", "updated_at"])

        display_name = creator_display_name(admin)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.EPISODE_UNPUBLISHED,
            description=(
                f"Episode '{episode.title}' was unpublished by {display_name}."  # noqa: E501
            ),
            actor=admin,
            metadata={
                "episode_id": str(episode.id),
                "title": episode.title,
            },
        )

        return episode

    def remove_episode(self, admin: AdminUser, episode_id: str) -> None:
        episode = self.content_repo.get_episode_by_id(episode_id)
        if not episode:
            raise ValidationError({"episode_id": "Episode not found."})

        # Check permission: creator or admin with CONTENT_MANAGE
        if episode.creator_id != admin.id and not admin.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied("You don't have permission to remove this episode.")

        episode_id_str = str(episode.id)
        episode_title = episode.title

        # Clean up Cloudinary assets if present
        if episode.video_public_id:
            try:
                delete_from_cloudinary(episode.video_public_id, "video")
            except Exception as e:
                logger.warning(f"Failed to delete video from Cloudinary: {e}")

        if episode.thumbnail_public_id:
            try:
                delete_from_cloudinary(episode.thumbnail_public_id)
            except Exception as e:
                logger.warning(f"Failed to delete thumbnail from Cloudinary: {e}")

        # Delete the episode
        episode.delete()

        display_name = creator_display_name(admin)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.EPISODE_REMOVED,
            description=(
                f"Episode '{episode_title}' was removed by {display_name}."  # noqa: E501
            ),
            actor=admin,
            subject=episode,
            metadata={"episode_id": episode_id_str, "title": episode_title},
        )
