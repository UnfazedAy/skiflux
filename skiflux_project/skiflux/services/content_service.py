import logging
import mimetypes
from datetime import date, timedelta
from decimal import Decimal
from decimal import Decimal as D
import uuid

from django.db import transaction
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from skiflux.models import (
    ActivityLog,
    AdminUser,
    Episode,
    EpisodeComment,
    EpisodePurchase,
    EpisodeTask,
    Permission,
    SkillcoinTransaction,
    SystemFinancialConfig,
    TaskSubmission,
    User,
    UserBehaviourLog,
)
from skiflux.models.platform_settings import SystemContentConfig
from skiflux.repositories.content_repository import (
    ContentRepository,
    episodes_for_serializer,
)
from skiflux.repositories.purchase_repository import PurchaseRepository
from skiflux.repositories.wallet_repository import WalletRepository
from skiflux.services.activity import ActivityService
from skiflux.services.creator_management_service import CreatorManagementService
from skiflux.services.notification_service import (
    NotificationService,
)
from skiflux.services.studio_service import ContentAccessService
from skiflux.tasks.moderation import moderate_comment_task
from skiflux.utils import get_private_avatar_url
from skiflux.services.gamification_service import GamificationService

from .wallet_service import WalletService

logger = logging.getLogger(__name__)


def compute_priority(submitted_at, now, sla_hours: int) -> str:
    elapsed = (now - submitted_at).total_seconds()
    sla_total = sla_hours * 3600
    pct = (elapsed / sla_total) * 100

    if pct >= 75:
        return "high"
    elif pct >= 50:
        return "medium"
    else:
        return "low"


class ContentService:
    WEIGHTS = {
        "view": 1.0,
        "like": 2.5,
        "save": 3.5,
        "comment": 2.0,
        "task_attempt": 4.0,
        "task_complete": 5.0,
    }

    def __init__(self):
        self.content_repo = ContentRepository()
        self.purchase_repo = PurchaseRepository()
        self.access_service = ContentAccessService()
        self.creator_management_service = CreatorManagementService()
        self.wallet_service = WalletService()

    def _can_view_content(self, admin: AdminUser) -> bool:
        return admin.has_permission(Permission.CONTENT_VIEW) or admin.has_permission(
            Permission.CONTENT_MANAGE
        )

    def _is_submission_creator(self, admin: AdminUser, submission: TaskSubmission):
        return submission.task.episode.creator_id == admin.id

    def _get_published_episode(self, episode_id: str) -> Episode:
        episode = self.content_repo.get_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")
        if episode.status != Episode.Status.PUBLISHED:
            raise ValidationError("Episode not found.")
        return episode

    def get_episode_with_access(self, user: User, episode_id: str) -> dict:
        episode = self.content_repo.get_episode(episode_id)

        if not episode or episode.status != Episode.Status.PUBLISHED:
            raise ValidationError("Episode not found.")

        can_access = self.access_service.can_user_access_episode(user, episode)
        return {"episode": episode, "can_access": can_access}

    @transaction.atomic
    def purchase_episode(self, user: User, episode_id: str) -> EpisodePurchase:
        episode = self.content_repo.get_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")
        if episode.access_type == Episode.AccessType.FREE:
            raise ValidationError("This episode is free, no purchase needed.")

        config = SystemFinancialConfig.get_config()
        price = config.episode_purchase_price_skillcoins
        purchase, created = self.purchase_repo.create(
            user=user,
            episode=episode,
            amount_paid=price,
        )
        if not created:
            raise ValidationError("You already own this episode.")

        purchase_refs = [purchase.id, episode.id]
        try:
            self.wallet_service.debit_wallet(
                owner=user,
                amount=price,
                tx_type=SkillcoinTransaction.Type.DEBIT_PURCHASE,
                description=(
                    f"Purchase Episode: '{episode.title}' "
                    f"(Season: '{episode.season.title}')"
                ),
                reference_id=purchase.id,
                idempotency_key=f"purchase-debit-{purchase.id}",
            )
            creator_share = (
                price * config.creator_share_percentage / Decimal("100.00")
            ).quantize(Decimal("0.01"))
            platform_share = price - creator_share
            desc_creator = (
                f"Creator Revenue Split ({config.creator_share_percentage}%) "
                f"for Episode: '{episode.title}' purchased by {user.email}"
            )

            if creator_share > Decimal("0.00"):
                self.wallet_service.credit_wallet(
                    owner=episode.creator,
                    amount=creator_share,
                    tx_type=SkillcoinTransaction.Type.CREATOR_REVENUE,
                    description=desc_creator,
                    reference_id=purchase.id,
                    idempotency_key=f"purchase-creator-credit-{purchase.id}",
                )

                try:
                    wallet_repo = WalletRepository()
                    creator_wallet = wallet_repo.get_wallet(
                        {"admin_user": episode.creator}
                    )
                    total = (
                        wallet_repo.get_posted_revenue_total_by_wallet(
                            creator_wallet, SkillcoinTransaction.Type.CREATOR_REVENUE
                        )
                        if creator_wallet
                        else D("0.00")
                    )
                    rev_thresholds = [
                        D("50"),
                        D("100"),
                        D("500"),
                        D("1000"),
                        D("5000"),
                        D("10000"),
                    ]
                    for thresh in rev_thresholds:
                        if total >= thresh and (total - creator_share) < thresh:
                            notif = NotificationService()
                            title = f"Revenue milestone: {thresh} Skillcoins"
                            body = (
                                f"You've earned {total} Skillcoins in creator revenue!"
                            )
                            notif.send_push_for_event(
                                admin_user=episode.creator,
                                event_type="revenue_milestone",
                                title=title,
                                body=body,
                                data={
                                    "episode_id": str(episode.id),
                                    "total_revenue": str(total),
                                    "milestone": str(thresh),
                                },
                            )
                            notif.create_notification(
                                admin_user=episode.creator,
                                type="revenue_milestone",
                                title=title,
                                body=body,
                                data={
                                    "episode_id": str(episode.id),
                                    "total_revenue": str(total),
                                },
                            )
                            break
                except Exception:
                    logger.warning("Failed revenue_milestone notify (non-fatal)")

            if platform_share > Decimal("0.00"):
                self.wallet_service.credit_platform_wallet(
                    amount=platform_share,
                    tx_type=SkillcoinTransaction.Type.PLATFORM_REVENUE,
                    description=f"Platform Revenue for Episode: '{episode.title}' purchased by {user.email}",  # noqa: E501
                    reference_id=purchase.id,
                    idempotency_key=f"purchase-platform-credit-{purchase.id}",
                )
        except Exception:
            purchase.status = EpisodePurchase.Status.CANCELLED
            purchase.save(update_fields=["status"])
            self.wallet_service.mark_transactions_status_by_reference(
                reference_ids=purchase_refs,
                from_status=SkillcoinTransaction.Status.POSTED,
                to_status=SkillcoinTransaction.Status.CANCELLED,
                transaction_types=[
                    SkillcoinTransaction.Type.DEBIT_PURCHASE,
                    SkillcoinTransaction.Type.CREATOR_REVENUE,
                    SkillcoinTransaction.Type.PLATFORM_REVENUE,
                ],
            )
            raise

        return purchase

    def list_user_purchases(self, user: User):
        return self.purchase_repo.list_by_user(user)

    def track_view(
        self,
        user: User,
        episode_id: str,
        watch_duration_seconds: int,
        completed: bool,
    ):
        from skiflux.models.app_preference import UserAppPreferences

        episode = self._get_published_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")
        if not self.access_service.can_user_access_episode(user, episode):
            raise PermissionDenied("Purchase this episode to watch it.")

        prefs = UserAppPreferences.get_or_create_for_user(user)
        GamificationService().process_daily_activity(user)

        if not prefs.save_watch_history:
            return None

        view = self.content_repo.upsert_view(
            user=user,
            episode=episode,
            watch_duration_seconds=watch_duration_seconds,
            completed=completed,
        )

        episode.refresh_from_db(fields=["view_count"])
        vc = getattr(episode, "view_count", 0)

        if prefs.personalised_recommendations:
            weight = 3.0 if completed else 1.0
            self.content_repo.create_behaviour_log(
                user=user,
                episode=episode,
                season=episode.season,
                skillworld=episode.season.skillworld,
                action=UserBehaviourLog.Action.VIEW,
                weight=weight,
            )
        thresholds = {10, 50, 100, 500, 1000, 5000, 10000}
        if vc in thresholds and episode.creator:
            try:
                notif = NotificationService()
                title = f"Milestone: {vc} views"
                body = f"Your episode '{episode.title}' reached {vc} views!"
                notif.send_push_for_event(
                    admin_user=episode.creator,
                    event_type="episode_reached_x_views",
                    title=title,
                    body=body,
                    data={"episode_id": str(episode.id), "view_count": vc},
                )
                notif.create_notification(
                    admin_user=episode.creator,
                    type="episode_reached_x_views",
                    title=title,
                    body=body,
                    data={"episode_id": str(episode.id), "view_count": vc},
                )

            except Exception:
                logger.warning("Failed episode_reached_x_views notify (non-fatal)")

        return view

    def toggle_like(self, user: User, episode_id: str):
        episode = self._get_published_episode(episode_id)
        is_liked = self.content_repo.toggle_like(user, episode)
        if is_liked:
            self.content_repo.create_behaviour_log(
                user=user,
                episode=episode,
                season=episode.season,
                skillworld=episode.season.skillworld,
                action=UserBehaviourLog.Action.LIKE,
                weight=self.WEIGHTS.get(UserBehaviourLog.Action.LIKE, 2.0),
            )
        return is_liked

    def toggle_save(self, user: User, episode_id: str):
        episode = self._get_published_episode(episode_id)

        if not episode:
            raise ValidationError("Episode not found.")
        is_saved = self.content_repo.toggle_save(user, episode)
        return is_saved

    def mark_not_interested(self, user: User, episode_id: str) -> dict:
        episode = self._get_published_episode(episode_id)
        created = self.content_repo.mark_not_interested(user, episode)
        return {
            "episode_id": str(episode.id),
            "removed": True,
            "already_marked": not created,
        }

    def _get_comment_or_raise(self, comment_id: int) -> EpisodeComment:
        comment = self.content_repo.get_comment_by_id(comment_id)
        if not comment:
            raise ValidationError("Comment not found.")
        return comment

    def _finalize_new_comment(
        self,
        user: User,
        episode: Episode,
        comment: EpisodeComment,
        audio_file=None,
    ) -> EpisodeComment:
        if audio_file:
            from skiflux.utils.media import upload_to_minio
            from skiflux.tasks.content import upload_media_from_minio_task

            minio_key = upload_to_minio(audio_file, folder="skiflux_comments")
            upload_media_from_minio_task.delay(
                instance_id=str(comment.id),
                minio_object_key=minio_key,
                field_name="audio_public_id",
                model_name="EpisodeComment",
                resource_type="video",
            )

        try:
            owner = episode.creator
            if owner:
                NotificationService().send_push_for_event(
                    admin_user=owner,
                    event_type="new_comment_on_episode",
                    title="New Comment on Your Episode",
                    body=f"{user.first_name or user.email} commented on '{episode.title}'",  # noqa: E501
                    data={"episode_id": str(episode.id), "comment_id": str(comment.id)},
                )
                NotificationService().create_notification(
                    admin_user=owner,
                    type="new_comment_on_episode",
                    title="New Comment on Your Episode",
                    body=f"{user.first_name or user.email} commented on '{episode.title}'",  # noqa: E501
                    data={"episode_id": str(episode.id)},
                )
        except Exception:
            logger.warning("Failed new_comment_on_episode notify (non-fatal)")

        moderate_comment_task.delay(str(comment.id))
        return comment

    def toggle_comment_like(self, user: User, comment_id: int) -> bool:
        comment = self._get_comment_or_raise(comment_id)
        self._get_published_episode(str(comment.episode_id))
        return self.content_repo.toggle_comment_like(user, comment)

    def delete_comment(self, user: User, comment_id: int) -> None:
        comment = self.content_repo.get_comment_by_id(comment_id)
        if not comment:
            raise ValidationError("Comment not found.")
        if comment.user_id != user.id:
            raise PermissionDenied("You can only delete your own comments.")
        self.content_repo.delete_comment(comment)

    def edit_comment(self, user: User, comment_id: int, text: str) -> EpisodeComment:
        comment = self.content_repo.get_comment_by_id(comment_id)
        if not comment:
            raise ValidationError("Comment not found.")
        if comment.user_id != user.id:
            raise PermissionDenied("You can only edit your own comments.")
        if not text:
            raise ValidationError("Comment text is required.")
        self._get_published_episode(str(comment.episode_id))
        comment = self.content_repo.update_comment(comment, text)
        moderate_comment_task.delay(str(comment.id))
        return comment

    def reply_to_comment(
        self,
        user: User,
        parent_comment_id: int,
        text: str = "",
        audio_file=None,
    ) -> EpisodeComment:
        parent = self._get_comment_or_raise(parent_comment_id)
        episode = self._get_published_episode(str(parent.episode_id))

        if not text and not audio_file:
            raise ValidationError(
                "A comment must contain either text or an audio recording."
            )

        comment = self.content_repo.add_comment(
            user=user,
            episode=episode,
            text=text,
            parent=parent,
        )
        return self._finalize_new_comment(user, episode, comment, audio_file=audio_file)

    def add_comment(self, user: User, episode_id: str, text: str = "", audio_file=None):
        episode = self._get_published_episode(episode_id)

        if not episode:
            raise ValidationError("Episode not found.")

        if not text and not audio_file:
            raise ValidationError(
                "A comment must contain either text or an audio recording."
            )

        comment = self.content_repo.add_comment(user, episode, text)
        return self._finalize_new_comment(user, episode, comment, audio_file=audio_file)

    def get_comments(self, episode_id: str):
        episode = self._get_published_episode(episode_id)

        if not episode:
            raise ValidationError("Episode not found.")
        return self.content_repo.get_comments(episode)

    def get_episode_tasks(self, user: User, episode_id: str) -> dict:
        episode = self._get_published_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")
        if not self.access_service.can_user_access_episode(user, episode):
            raise PermissionDenied("You must purchase this episode to view its tasks.")

        project_task = self.content_repo.get_task_by_kind(
            episode, EpisodeTask.Kind.PROJECT_BASED
        )
        assessment_task = self.content_repo.get_task_by_kind(
            episode, EpisodeTask.Kind.ASSESSMENT
        )

        from skiflux.models import EpisodeView

        view = EpisodeView.objects.filter(user=user, episode=episode).first()
        viewed_at = view.viewed_at if view else None

        my_project_submission = None
        my_assessment_submissions = []
        if project_task:
            project_task.current_user_submissions = list(
                project_task.submissions.filter(user=user)
            )
            status, _, _ = self._get_user_task_status(project_task, viewed_at)
            project_task.status = status

            my_project_submission = self.content_repo.get_user_project_submission(
                project_task, user
            )
        if assessment_task:
            assessment_task.current_user_assessment_submissions = list(
                assessment_task.assessment_submissions.filter(user=user).order_by(
                    "-submitted_at"
                )
            )
            status, _, _ = self._get_user_task_status(assessment_task, viewed_at)
            assessment_task.status = status

            my_assessment_submissions = (
                self.content_repo.get_user_assessment_submissions(
                    assessment_task, user, limit=5
                )
            )

        return {
            "project_task": project_task,
            "assessment_task": assessment_task,
            "my_project_submission": my_project_submission,
            "my_assessment_submissions": my_assessment_submissions,
        }

    def _get_user_task_status(self, task: EpisodeTask, viewed_at):
        now = timezone.now()
        sla_deadline = None
        if viewed_at:
            sla_deadline = viewed_at + timedelta(hours=task.sla_time_limit_hours or 24)

        if task.kind == EpisodeTask.Kind.PROJECT_BASED:
            submissions = getattr(task, "current_user_submissions", [])
            submission = submissions[0] if submissions else None
            if submission:
                if submission.status == TaskSubmission.Status.APPROVED:
                    return "completed", sla_deadline, submission
                if submission.status == TaskSubmission.Status.REJECTED:
                    return "rejected", sla_deadline, submission
                return "pending_review", sla_deadline, submission

            if sla_deadline and now > sla_deadline:
                return "overdue", sla_deadline, None
            return "pending", sla_deadline, None

        submissions = getattr(task, "current_user_assessment_submissions", [])
        submission = submissions[0] if submissions else None
        if submission:
            status = "completed" if submission.passed else "rejected"
            return status, sla_deadline, submission

        if sla_deadline and now > sla_deadline:
            return "overdue", sla_deadline, None
        return "pending", sla_deadline, None

    def get_tasks_for_viewed_episodes(
        self,
        user: User,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        qs = self.content_repo.get_tasks_for_viewed_episodes(user)
        total_count = qs.count()
        tasks = qs[offset : offset + limit]

        results = []
        for task in tasks:
            viewed_at = getattr(task, "viewed_at", None)
            status, sla_deadline, submission = self._get_user_task_status(
                task,
                viewed_at,
            )
            submitted_at = None
            reviewed_at = None
            if submission is not None:
                submitted_at = getattr(
                    submission,
                    "created_at",
                    getattr(submission, "submitted_at", None),
                )
                reviewed_at = getattr(submission, "reviewed_at", None)

            questions = None
            if task.kind == EpisodeTask.Kind.ASSESSMENT:
                questions = list(getattr(task, "prefetched_questions", []))

            results.append(
                {
                    "id": str(task.id),
                    "episode_id": str(task.episode_id),
                    "episode_title": task.episode.title,
                    "season_id": str(task.episode.season_id),
                    "season_title": task.episode.season.title,
                    "kind": task.kind,
                    "status": status,
                    "sla_time_limit_hours": task.sla_time_limit_hours,
                    "sla_deadline": sla_deadline,
                    "task_brief": task.task_brief,
                    "accepted_proof_types": task.accepted_proof_types,
                    "pass_score_percent": task.pass_score_percent,
                    "time_limit_minutes": task.time_limit_minutes,
                    "max_attempts": task.max_attempts,
                    "completion_criteria": task.completion_criteria,
                    "questions": questions,
                    "viewed_at": viewed_at,
                    "submitted_at": submitted_at,
                    "reviewed_at": reviewed_at,
                }
            )

        return {
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "results": results,
        }

    @transaction.atomic
    def submit_tasks(
        self,
        user: User,
        episode_id: str,
        project_submission_data: dict = None,
        assessment_submission_data: dict = None,
    ):
        episode = self._get_published_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")
        if not self.access_service.can_user_access_episode(user, episode):
            raise PermissionDenied("You must purchase this episode to submit tasks.")

        result = {"project_submission_id": None, "assessment_submission_id": None}

        if project_submission_data:
            pt = self.content_repo.get_task_by_kind(
                episode, EpisodeTask.Kind.PROJECT_BASED
            )
            if not pt:
                raise ValidationError("No project task found for this episode.")
            if self.content_repo.submission_exists(user, pt):
                raise ValidationError("You have already submitted the project task.")

            url = project_submission_data.get("submission_url")
            submission_file = project_submission_data.get("submission_file")
            if not url and not submission_file:
                raise ValidationError(
                    "Either submission_url or submission_file is required "
                    "for project tasks."
                )

            file_name = None
            file_content_type = None
            if submission_file:
                file_name = submission_file.name
                file_content_type = getattr(
                    submission_file,
                    "content_type",
                    mimetypes.guess_type(submission_file.name)[0]
                    or "application/octet-stream",
                )
                from skiflux.utils.media import (
                    derive_submission_proof_type,
                    proof_type_allowed,
                )

                preview = TaskSubmission(
                    submission_url=url,
                    submission_file_content_type=file_content_type,
                )
                derived_proof_type = derive_submission_proof_type(preview)
                if not proof_type_allowed(derived_proof_type, pt.accepted_proof_types):
                    raise ValidationError(
                        f"This task does not accept '{derived_proof_type}' submissions."
                    )
            elif url:
                from skiflux.utils.media import proof_type_allowed

                if not proof_type_allowed("link", pt.accepted_proof_types):
                    raise ValidationError("This task does not accept link submissions.")

            sub = self.content_repo.create_submission(
                task=pt,
                user=user,
                submission_text=project_submission_data.get("submission_text", ""),
                submission_url=url,
                submission_file_name=file_name,
                submission_file_content_type=file_content_type,
            )

            if submission_file:
                from skiflux.utils.media import (
                    cloudinary_resource_type_for_submission_file,
                    upload_to_minio,
                )
                from skiflux.tasks.content import upload_media_from_minio_task

                minio_key = upload_to_minio(
                    submission_file,
                    folder="skiflux_task_submissions",
                )
                upload_media_from_minio_task.delay(
                    instance_id=str(sub.id),
                    minio_object_key=minio_key,
                    field_name="submission_file_public_id",
                    model_name="TaskSubmission",
                    resource_type=cloudinary_resource_type_for_submission_file(
                        file_content_type
                    ),
                    content_type=file_content_type,
                )
            result["project_submission_id"] = str(sub.id)
            result["project_status"] = "pending_review"

            GamificationService().process_daily_activity(user)

            try:
                NotificationService().send_push_for_event(
                    admin_user=episode.creator,
                    event_type="task_submission_received",
                    title="New Task Submission",
                    body=f"{user.email} submitted a project task for '{episode.title}'.",  # noqa: E501
                    data={
                        "type": "submission_received",
                        "episode_id": str(episode.id),
                        "submission_id": str(sub.id),
                        "user_email": user.email,
                    },
                )
                NotificationService().create_notification(
                    admin_user=episode.creator,
                    type="task_submission_received",
                    title="New Task Submission",
                    body=f"{user.email} submitted a project task for '{episode.title}'.",  # noqa: E501
                    data={
                        "episode_id": str(episode.id),
                        "submission_id": str(sub.id),
                        "user_email": user.email,
                    },
                )
            except Exception:
                logger.warning("Push notify creator of submission failed (non-fatal)")

            self.content_repo.create_behaviour_log(
                user=user,
                episode=episode,
                season=episode.season,
                skillworld=episode.season.skillworld,
                action=UserBehaviourLog.Action.TASK_ATTEMPT,
                weight=self.WEIGHTS.get(UserBehaviourLog.Action.TASK_ATTEMPT, 4.0),
            )

        if assessment_submission_data:
            at = self.content_repo.get_task_by_kind(
                episode, EpisodeTask.Kind.ASSESSMENT
            )
            if not at:
                raise ValidationError("No assessment task found for this episode.")

            attempts = self.content_repo.get_assessment_attempt_count(user, at)
            if at.max_attempts and attempts >= at.max_attempts:
                raise ValidationError("Maximum attempts reached for this assessment.")

            user_answers = assessment_submission_data.get("answers", {})
            questions = at.questions.all()

            if not questions.exists():
                raise ValidationError("This assessment has no questions.")

            correct_count = 0
            for q in questions:
                if (
                    str(q.id) in user_answers
                    and user_answers[str(q.id)] == q.correct_answer
                ):
                    correct_count += 1

            score_percent = (correct_count / questions.count()) * 100
            passed = score_percent >= at.pass_score_percent

            sub = self.content_repo.create_assessment_submission(
                task=at,
                user=user,
                score_percent=score_percent,
                passed=passed,
                answers=user_answers,
                attempt_number=attempts + 1,
                cashback_amount=0.0,
                time_taken_seconds=assessment_submission_data.get("time_taken_seconds"),
            )
            result["assessment_submission_id"] = str(sub.id)

            self.content_repo.create_behaviour_log(
                user=user,
                episode=episode,
                season=episode.season,
                skillworld=episode.season.skillworld,
                action=UserBehaviourLog.Action.TASK_ATTEMPT,
                weight=self.WEIGHTS.get(UserBehaviourLog.Action.TASK_ATTEMPT, 4.0),
            )

            if passed:
                self.content_repo.create_behaviour_log(
                    user=user,
                    episode=episode,
                    season=episode.season,
                    skillworld=episode.season.skillworld,
                    action=UserBehaviourLog.Action.TASK_COMPLETE,
                    weight=self.WEIGHTS.get(UserBehaviourLog.Action.TASK_COMPLETE, 5.0),
                )

                gamification_service = GamificationService()
                gamification_service.process_daily_activity(user)
                gamification_service.add_xp(user, 20)  # Standard XP for assessment task

                try:
                    config = SystemFinancialConfig.get_config()
                    cb = config.assessment_task_cashback_amount or Decimal("0.00")
                    if cb > 0:
                        already_awarded = (
                            self.content_repo.has_awarded_cashback_for_assessment(
                                at, user
                            )
                        )
                        if not already_awarded:
                            self.wallet_service.debit_platform_wallet(
                                amount=cb,
                                tx_type=SkillcoinTransaction.Type.PLATFORM_CASHBACK_DEBIT,
                                description=f"Platform Cashback for Assessment on '{episode.title}'",  # noqa: E501
                                reference_id=sub.id,
                                admin_user=None,
                                idempotency_key=f"assessment-platform-debit-{sub.id}",
                            )
                            self.wallet_service.credit_wallet(
                                owner=user,
                                amount=cb,
                                tx_type=SkillcoinTransaction.Type.CASHBACK_REWARD,
                                description=f"Cashback Reward for passing Assessment on '{episode.title}'",  # noqa: E501
                                reference_id=sub.id,
                                admin_user=None,
                                idempotency_key=f"assessment-credit-{sub.id}",
                            )
                            sub.cashback_amount = cb
                            sub.save(update_fields=["cashback_amount"])
                except Exception as exc:
                    logger.warning(
                        "Failed to award assessment cashback (non-fatal): %s", exc
                    )

                try:
                    NotificationService().send_push_for_event(
                        user=user,
                        event_type="task_approved_with_coins",
                        title="Assessment Passed",
                        body=f"You passed the assessment for '{episode.title}' with {sub.score_percent:.0f}%. +{sub.cashback_amount} coins!",  # noqa: E501
                        data={
                            "type": "assessment_passed",
                            "episode_id": str(episode.id),
                            "submission_id": str(sub.id),
                            "score": str(sub.score_percent),
                            "cashback_amount": str(sub.cashback_amount),
                        },
                    )
                    NotificationService().create_notification(
                        user=user,
                        type="task_approved_with_coins",
                        title="Assessment Passed",
                        body=f"You passed the assessment for '{episode.title}' with {sub.score_percent:.0f}%. +{sub.cashback_amount} coins!",  # noqa: E501
                        data={
                            "episode_id": str(episode.id),
                            "submission_id": str(sub.id),
                            "score": str(sub.score_percent),
                            "cashback_amount": str(sub.cashback_amount),
                        },
                    )
                except Exception:
                    logger.warning("Push for assessment pass failed (non-fatal)")

                result["assessment_result"] = {
                    "score_percent": sub.score_percent,
                    "passed": sub.passed,
                    "cashback_amount": str(sub.cashback_amount),
                    "attempt_number": sub.attempt_number,
                }
                if sub.score_percent >= 100:
                    try:
                        NotificationService().send_push_for_event(
                            user=user,
                            event_type="assessment_perfect_score",
                            title="Perfect Score!",
                            body=f"100% on {episode.title} assessment!",
                            data={"episode_id": str(episode.id), "score": 100},
                        )
                        NotificationService().create_notification(
                            user=user,
                            type="assessment_perfect_score",
                            title="Perfect Score!",
                            body=f"100% on {episode.title} assessment!",
                            data={"episode_id": str(episode.id)},
                        )
                    except Exception:
                        logger.warning("Failed perfect score notify (non-fatal)")
                try:
                    today_str = date.today().isoformat()
                    cache_key = f"streak_maintained_sent_{user.id}_{today_str}"
                    if not cache.get(cache_key):
                        streak = UserBehaviourLog.compute_current_streak(user)
                        if streak >= 2:
                            cache.set(cache_key, True, timeout=86400)
                            NotificationService().send_push_for_event(
                                user=user,
                                event_type="streak_maintained",
                                title="Streak maintained!",
                                body=f"{streak}-day learning streak. Great work!",
                                data={"streak_days": streak},
                            )
                            NotificationService().create_notification(
                                user=user,
                                type="streak_maintained",
                                title="Streak maintained!",
                                body=f"{streak}-day learning streak. Great work!",
                                data={"streak_days": streak},
                            )
                except Exception:
                    logger.warning(
                        "Failed streak_maintained (assessment) notify (non-fatal)"
                    )
            else:
                result["assessment_result"] = {
                    "score_percent": sub.score_percent,
                    "passed": sub.passed,
                    "cashback_amount": "0.00",
                    "attempt_number": sub.attempt_number,
                }

        return result

    @transaction.atomic
    def approve_submission(
        self,
        admin,
        submission_id: str,
        cashback_amount: float = None,
        feedback: str = None,
    ):
        if not isinstance(admin, AdminUser):
            raise PermissionDenied("Only admin users can approve submissions.")
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied("You do not have permission to approve submissions.")

        config = SystemFinancialConfig.get_config()
        if cashback_amount is not None:
            cashback = Decimal(str(cashback_amount))
        else:
            cashback = config.project_task_cashback_amount or Decimal("0.00")
        if cashback < Decimal("0.00"):
            raise ValidationError(
                {"cashback_amount": "Cashback amount cannot be negative."}
            )
        max_cashback = Decimal(str(config.max_cashback_amount))
        if cashback > max_cashback:
            raise ValidationError(
                {
                    "cashback_amount": (
                        f"Cashback cannot exceed {max_cashback} Skillcoins."
                    )
                }
            )

        submission = self.content_repo.get_task_submission_for_review(submission_id)
        if not submission:
            raise ValidationError("Submission not found.")

        if not self._is_submission_creator(
            admin, submission
        ) and not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied(
                "You do not own this submission's task or "
                "have permission to approve submissions."
            )

        if submission.status == TaskSubmission.Status.APPROVED:
            raise ValidationError("This submission has already been approved.")
        if submission.task.episode.access_type == Episode.AccessType.FREE:
            raise ValidationError("Cannot award cashback for a free episode.")

        # credit_wallet already posts a corresponding negative liability entry on the
        # platform wallet, so no separate debit_platform_wallet call is needed here.
        self.wallet_service.credit_wallet(
            owner=submission.user,
            amount=cashback,
            tx_type=SkillcoinTransaction.Type.CASHBACK_REWARD,
            description=f"Cashback Reward for Task Submission '{submission.task.episode.title}'",  # noqa: E501
            reference_id=submission.id,
            admin_user=admin,
            idempotency_key=f"cashback-credit-{submission.id}",
        )
        submission.status = TaskSubmission.Status.APPROVED
        submission.cashback_amount = cashback
        submission.feedback = feedback
        submission.rejection_reason = None
        submission.reviewed_by = admin
        submission.reviewed_at = timezone.now()
        submission.save(
            update_fields=[
                "status",
                "cashback_amount",
                "feedback",
                "rejection_reason",
                "reviewed_by",
                "reviewed_at",
            ]
        )

        GamificationService().add_xp(
            submission.user, 20
        )  # Standard XP for project task

        try:
            NotificationService().send_push_for_event(
                user=submission.user,
                event_type="task_approved_with_coins",
                title="Task Approved",
                body=f"Your submission for '{submission.task.episode.title}' was approved. +{cashback} coins!",  # noqa: E501
                data={
                    "type": "task_approved",
                    "episode_id": str(submission.task.episode.id),
                    "submission_id": str(submission.id),
                    "cashback_amount": str(cashback),
                },
            )
            NotificationService().create_notification(
                user=submission.user,
                type="task_approved_with_coins",
                title="Task Approved",
                body=f"Your submission for '{submission.task.episode.title}' was approved. +{cashback} coins!",  # noqa: E501
                data={
                    "episode_id": str(submission.task.episode.id),
                    "submission_id": str(submission.id),
                    "cashback_amount": str(cashback),
                },
            )
        except Exception:
            logger.warning("Failed task approved notify (non-fatal)")

        self.content_repo.create_behaviour_log(
            user=submission.user,
            episode=submission.task.episode,
            season=submission.task.episode.season,
            skillworld=submission.task.episode.season.skillworld,
            action=UserBehaviourLog.Action.TASK_COMPLETE,
            weight=5.0,
        )

        try:
            completed_count = self.content_repo.get_completed_tasks_count(
                submission.user
            )
            if completed_count % 5 == 0:
                NotificationService().send_push_for_event(
                    user=submission.user,
                    event_type="milestone_badge_earned",
                    title="Milestone Achieved!",
                    body=f"You've completed {completed_count} tasks!",
                    data={
                        "count": completed_count,
                        "badge": f"{completed_count}_tasks",
                    },
                )
                NotificationService().create_notification(
                    user=submission.user,
                    type="milestone_badge_earned",
                    title="Milestone Achieved!",
                    body=f"You've completed {completed_count} tasks!",
                    data={"count": completed_count},
                )
        except Exception:
            logger.warning("Failed milestone notify (non-fatal)")

        try:
            today_str = date.today().isoformat()
            cache_key = f"streak_maintained_sent_{submission.user.id}_{today_str}"
            if not cache.get(cache_key):
                streak = UserBehaviourLog.compute_current_streak(submission.user)
                if streak >= 2:
                    cache.set(cache_key, True, timeout=86400)
                    NotificationService().send_push_for_event(
                        user=submission.user,
                        event_type="streak_maintained",
                        title="Streak maintained!",
                        body=f"{streak}-day learning streak. Great work!",
                        data={"streak_days": streak},
                    )
                    NotificationService().create_notification(
                        user=submission.user,
                        type="streak_maintained",
                        title="Streak maintained!",
                        body=f"{streak}-day learning streak. Great work!",
                        data={"streak_days": streak},
                    )
        except Exception:
            logger.warning("Failed streak_maintained notify (non-fatal)")

        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.CONTENT_APPROVED,
            description=(
                f"{submission.user.email} task submission was approved for "
                f"{submission.task.episode.title}."
            ),
            actor=admin,
            subject=submission.user,
            metadata={
                "submission_id": str(submission.id),
                "episode_id": str(submission.task.episode.id),
                "episode_title": submission.task.episode.title,
                "cashback_amount": str(cashback),
                "feedback": feedback,
            },
        )
        return submission

    def get_submission_for_review(self, admin, submission_id: str) -> TaskSubmission:
        if not isinstance(admin, AdminUser):
            raise PermissionDenied("Only admin users can review submissions.")

        submission = self.content_repo.get_submission(submission_id)
        if not submission:
            raise ValidationError("Submission not found.")
        if not self._is_submission_creator(
            admin, submission
        ) and not self._can_view_content(admin):
            raise PermissionDenied(
                "You do not own this submission's task or "
                "have permission to review submissions."
            )
        return submission

    @transaction.atomic
    def reject_submission(
        self,
        admin: AdminUser,
        submission_id: str,
        rejection_reason: str,
        feedback: str = None,
    ):
        if not isinstance(admin, AdminUser):
            raise PermissionDenied("Only admin users can reject submissions.")
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied("You do not have permission to reject submissions.")

        submission = self.content_repo.get_task_submission_for_review(submission_id)
        if not submission:
            raise ValidationError("Submission not found.")

        if submission.status != TaskSubmission.Status.PENDING:
            raise ValidationError("Only pending submissions can be rejected.")

        if not rejection_reason or not rejection_reason.strip():
            raise ValidationError(
                {"rejection_reason": "A rejection reason is required."}
            )

        self.content_repo.mark_submission_rejected(
            submission, admin, rejection_reason.strip(), feedback=feedback
        )

        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.CONTENT_REJECTED,
            description=(
                f"{submission.user.email} task submission was rejected for "
                f"{submission.task.episode.title}."
            ),
            actor=admin,
            subject=submission.user,
            metadata={
                "submission_id": str(submission.id),
                "episode_id": str(submission.task.episode.id),
                "episode_title": submission.task.episode.title,
                "reason": rejection_reason.strip()[:200],
                "feedback": feedback,
            },
        )

        def _notify_learner_rejected():
            try:
                NotificationService().send_push_for_event(
                    user=submission.user,
                    event_type="task_rejected_with_feedback",
                    title="Task Needs Revision",
                    body=f"Your submission for '{submission.task.episode.title}' was rejected. Reason: {rejection_reason.strip()[:120]}",  # noqa: E501
                    data={
                        "type": "task_rejected",
                        "episode_id": str(submission.task.episode.id),
                        "submission_id": str(submission.id),
                        "reason": rejection_reason.strip()[:200],
                        "feedback": feedback,
                    },
                )
                NotificationService().create_notification(
                    user=submission.user,
                    type="task_rejected_with_feedback",
                    title="Task Needs Revision",
                    body=f"Your submission for '{submission.task.episode.title}' was rejected. Reason: {rejection_reason.strip()[:120]}",  # noqa: E501
                    data={
                        "episode_id": str(submission.task.episode.id),
                        "submission_id": str(submission.id),
                        "reason": rejection_reason.strip()[:200],
                        "feedback": feedback,
                    },
                )
            except Exception:
                logger.warning("Push notify rejected submission failed (non-fatal)")

        transaction.on_commit(_notify_learner_rejected)
        return submission

    def get_published_seasons(self, skillworld=None):
        return self.content_repo.get_published_seasons(skillworld=skillworld)

    def _get_listed_creator_or_raise(self, creator_id: str):
        from skiflux.models.admin_user import AdminUser

        creator = self.creator_management_service.creator_repo.get_by_id(creator_id)
        if (
            not creator
            or not creator.is_listed_creator
            or creator.status
            in (AdminUser.Status.DEACTIVATED, AdminUser.Status.SUSPENDED)
        ):
            raise ValidationError("Creator not found.")
        return creator

    def get_creator_published_seasons(self, creator_id: str, skillworld=None):
        creator = self._get_listed_creator_or_raise(creator_id)
        return self.content_repo.get_published_seasons_by_creator(
            creator,
            skillworld=skillworld,
        )

    def get_creator_published_episodes(self, creator_id: str, skillworld=None):
        creator = self._get_listed_creator_or_raise(creator_id)
        return self.content_repo.get_published_episodes_by_creator(
            creator,
            skillworld=skillworld,
        )

    def get_season_episodes(self, season_id: str):
        season = self.content_repo.get_season_by_id(season_id)
        if not season or not season.is_published:
            raise ValidationError({"season_id": "Season not found."})

        return (
            episodes_for_serializer()
            .filter(season=season, status=Episode.Status.PUBLISHED)
            .order_by("order")
        )

    def get_learner_episode(self, user: User, episode_id: str) -> Episode:
        episode = (
            episodes_for_serializer()
            .filter(id=episode_id, status=Episode.Status.PUBLISHED)
            .select_related("season")
            .first()
        )
        if not episode or not episode.season.is_published:
            raise ValidationError("Episode not found.")

        if not self.access_service.can_user_access_episode(user, episode):
            raise PermissionDenied("Purchase required to access this episode.")

        return episode

    @transaction.atomic
    def refund_episode_purchase(self, admin: AdminUser, purchase_id: str) -> dict:
        if not isinstance(admin, AdminUser) or not admin.has_permission(
            Permission.ECONOMY_MANAGE
        ):
            raise PermissionDenied(
                "You do not have administrative clearance to issue refunds."
            )
        purchase_repo = PurchaseRepository()
        purchase = purchase_repo.get_purchase_by_id(purchase_id)
        if not purchase:
            raise ValidationError("Purchase record not found.")

        if purchase.status != EpisodePurchase.Status.ACTIVE:
            raise ValidationError("Only active purchases can be refunded.")

        user = purchase.user
        episode = purchase.episode
        refund_amount = Decimal(str(purchase.amount_paid))

        wallet_repo = WalletRepository()
        creator_wallet = wallet_repo.get_wallet({"admin_user": episode.creator})
        creator_tx = wallet_repo.get_transaction_by_reference(
            reference_id=purchase.id,
            transaction_type=SkillcoinTransaction.Type.CREATOR_REVENUE,
            wallet=creator_wallet,
        )
        platform_wallet, _ = wallet_repo.get_platform_wallet()
        platform_tx = wallet_repo.get_transaction_by_reference(
            reference_id=purchase.id,
            transaction_type=SkillcoinTransaction.Type.PLATFORM_REVENUE,
            wallet=platform_wallet,
        )

        purchase_refs = [purchase.id, episode.id]

        self.wallet_service.credit_wallet(
            owner=user,
            amount=refund_amount,
            tx_type=SkillcoinTransaction.Type.REFUND,
            description=f"Refund: Purchase of Episode '{episode.title}' reversed",
            reference_id=purchase.id,
            admin_user=admin,
            idempotency_key=f"refund-credit-{purchase.id}",
        )

        if creator_tx and creator_tx.amount > Decimal("0.00"):
            self.wallet_service.debit_wallet(
                owner=episode.creator,
                amount=creator_tx.amount,
                tx_type=SkillcoinTransaction.Type.CREATOR_REVENUE_REVERSAL,
                description=(
                    f"Refund clawback: creator revenue reversed for "
                    f"Episode '{episode.title}'"
                ),
                reference_id=purchase.id,
                admin_user=admin,
                idempotency_key=f"refund-creator-debit-{purchase.id}",
            )

        if platform_tx and platform_tx.amount > Decimal("0.00"):
            self.wallet_service.debit_platform_wallet(
                amount=platform_tx.amount,
                tx_type=SkillcoinTransaction.Type.ADMIN_ADJUSTMENT,
                description=f"Refund clawback: platform revenue reversed for Episode '{episode.title}'",  # noqa: E501
                reference_id=purchase.id,
                admin_user=admin,
                idempotency_key=f"refund-platform-debit-{purchase.id}",
            )

        self.wallet_service.mark_transactions_status_by_reference(
            reference_ids=purchase_refs,
            from_status=SkillcoinTransaction.Status.POSTED,
            to_status=SkillcoinTransaction.Status.REFUNDED,
            transaction_types=[
                SkillcoinTransaction.Type.DEBIT_PURCHASE,
                SkillcoinTransaction.Type.CREATOR_REVENUE,
                SkillcoinTransaction.Type.PLATFORM_REVENUE,
            ],
        )

        purchase.status = EpisodePurchase.Status.REFUNDED
        purchase.refunded_at = timezone.now()
        purchase.save(update_fields=["status", "refunded_at"])
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.REFUND_ISSUED,
            description=f"{user.email} was refunded for {episode.title}.",
            actor=admin,
            subject=user,
            metadata={
                "purchase_id": str(purchase.id),
                "episode_id": str(episode.id),
                "episode_title": episode.title,
                "amount_refunded": str(refund_amount),
            },
        )

        purchase_data = {
            "id": purchase.id,
            "user_email": user.email,
            "episode_title": episode.title,
            "amount_refunded": refund_amount,
            "purchase_status": purchase.status,
        }
        logger.info(
            "Episode purchase %s refunded successfully by admin %s.",
            purchase_id,
            admin.email,
        )
        return purchase_data

    def toggle_follow(self, user, creator_id: str) -> dict:
        creator = self.creator_management_service.creator_repo.get_by_id(creator_id)
        if not creator:
            raise ValidationError("Creator not found.")

        is_following = self.content_repo.toggle_follow(user, creator)

        self.creator_management_service.invalidate_creator_analytics_cache(
            str(creator_id)
        )
        if is_following:
            try:
                NotificationService().send_push_for_event(
                    admin_user=creator,
                    event_type="new_follower",
                    title="New Follower",
                    body=f"{user.first_name or user.email} is now following you!",
                    data={"follower_id": str(user.id)},
                )
                NotificationService().create_notification(
                    admin_user=creator,
                    type="new_follower",
                    title="New Follower",
                    body=f"{user.first_name or user.email} is now following you!",
                    data={"follower_id": str(user.id)},
                )
            except Exception:
                logger.warning("Failed new_follower notify (non-fatal)")

            from skiflux.utils.platform_task_tracker import trigger_platform_task

            trigger_platform_task(user, "follow_creator")

        return {
            "is_following": is_following,
            "creator_id": creator.id,
            "followers_count": self.content_repo.get_followers_count(creator),
        }

    def get_followed_creators(self, user):
        return self.content_repo.get_followed_creators(user)

    def get_public_creator_profile(self, user, creator_id: str) -> dict:
        creator = self.creator_management_service.creator_repo.get_by_id(creator_id)
        if (
            not creator
            or not creator.is_listed_creator
            or creator.status
            in (AdminUser.Status.DEACTIVATED, AdminUser.Status.SUSPENDED)
        ):
            raise ValidationError("Creator not found.")

        return {
            "id": str(creator.id),
            "username": creator.username,
            "first_name": creator.first_name,
            "last_name": creator.last_name,
            "display_name": creator.display_name,
            "avatar_url": get_private_avatar_url(creator.avatar_public_id),
            "bio": creator.bio,
            "skillworld": creator.skillworld,
            "followers_count": self.content_repo.get_followers_count(creator),
            "is_following": self.content_repo.is_following(user, creator),
            "notification_mode": self._creator_notification_mode(user, creator),
        }

    def _creator_notification_mode(self, user, creator) -> str | None:
        if not self.content_repo.is_following(user, creator):
            return None
        follow = self.content_repo.get_follow(user, creator)
        return follow.notification_mode if follow else None

    def get_creator_notification_preference(self, user, creator_id: str) -> dict:
        creator = self.creator_management_service.creator_repo.get_by_id(creator_id)
        if not creator or not creator.is_listed_creator:
            raise ValidationError("Creator not found.")
        follow = self.content_repo.get_follow(user, creator)
        if not follow:
            raise ValidationError("You are not following this creator.")
        return {
            "creator_id": str(creator.id),
            "mode": follow.notification_mode,
        }

    def update_creator_notification_preference(
        self, user, creator_id: str, mode: str
    ) -> dict:
        creator = self.creator_management_service.creator_repo.get_by_id(creator_id)
        if not creator or not creator.is_listed_creator:
            raise ValidationError("Creator not found.")
        follow = self.content_repo.update_creator_notification_mode(user, creator, mode)
        if not follow:
            raise ValidationError("You are not following this creator.")
        return {
            "creator_id": str(creator.id),
            "mode": follow.notification_mode,
        }

    def get_latest_followed_episodes(self, user):
        return self.content_repo.get_latest_followed_episodes(user)

    def rate_episode(self, user, episode_id: str, score: int, review: str = None):
        episode = self.content_repo.get_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")

        if episode.status != Episode.Status.PUBLISHED:
            raise ValidationError("Episode not found.")

        if not self.content_repo.has_purchased_episode(user, episode):
            raise PermissionDenied("You must purchase this episode to rate it.")

        rating, _ = self.content_repo.rate_episode(
            user=user,
            episode=episode,
            score=score,
            review=review,
        )

        self.creator_management_service.invalidate_creator_analytics_cache(
            str(episode.creator_id)
        )

        return rating

    def get_episodes_under_review_queryset(self, admin: AdminUser):
        if not isinstance(admin, AdminUser):
            raise PermissionDenied("Only admin users can list episodes under review.")
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied(
                "You do not have permission to view episodes under review."
            )
        return self.content_repo.get_episodes_under_review()

    @transaction.atomic
    def review_episode(
        self,
        admin: AdminUser,
        episode_id: str,
        action: str,
        rejection_reason: str = None,
    ) -> Episode:
        if not isinstance(admin, AdminUser):
            raise PermissionDenied("Only admin users can review episodes.")
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied("You do not have permission to review episodes.")

        episode = self.content_repo.get_episode_under_review(episode_id)
        if not episode:
            raise ValidationError("Episode not found or is not currently under review.")

        from skiflux.utils.media import (
            creator_display_name,
            send_content_approved_email,
            send_content_rejected_email,
        )

        now = timezone.now()
        if action == "approve":
            episode.status = Episode.Status.PUBLISHED
            episode.reviewed_by = admin
            episode.reviewed_at = now
            episode.rejection_reason = None
            episode.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            try:
                send_content_approved_email(
                    email=episode.creator.email,
                    episode_name=episode.title,
                    creator_name=creator_display_name(episode.creator),
                    episode_id=str(episode.id),
                )
            except Exception:
                logger.error(
                    "Failed to send approval email for episode %s",
                    episode_id,
                    exc_info=True,
                )  # noqa: E501
                pass

            try:
                NotificationService().send_push_for_event(
                    admin_user=episode.creator,
                    event_type="episode_approved",
                    title="Episode Approved",
                    body=f"'{episode.title}' has been approved and is now live.",
                    data={"type": "episode_approved", "episode_id": str(episode.id)},
                )
                NotificationService().create_notification(
                    admin_user=episode.creator,
                    type="episode_approved",
                    title="Episode Approved",
                    body=f"'{episode.title}' has been approved and is now live.",
                    data={"episode_id": str(episode.id)},
                )
            except Exception:
                logger.warning("Push for episode approved failed (non-fatal)")

            try:
                repo = ContentRepository()
                followers = repo.get_followers_with_notifications(episode.creator)
                notif = NotificationService()
                payload = {
                    "episode_id": str(episode.id),
                    "episode_title": episode.title,
                    "creator_id": str(episode.creator.id),
                }
                title = f"New episode from {episode.creator}"
                body = f"'{episode.title}' is now live."
                for f in followers:
                    notif.create_notification(
                        user=f,
                        type="followed_creator_new_episode",
                        title=title,
                        body=body,
                        data=payload,
                    )
                    notif.send_push_for_event(
                        user=f,
                        event_type="followed_creator_new_episode",
                        title=title,
                        body=body,
                        data=payload,
                    )
            except Exception:
                logger.warning(
                    "Failed follower notify on direct publish %s", episode.id
                )

            from skiflux.services.season_publish_service import SeasonPublishService

            SeasonPublishService().maybe_publish_season_for_episode(episode)

        elif action == "reject":
            if not rejection_reason:
                raise ValidationError(
                    {
                        "rejection_reason": "A rejection reason is required when rejecting an episode."  # noqa: E501
                    }
                )
            episode.status = Episode.Status.REJECTED
            episode.reviewed_by = admin
            episode.reviewed_at = now
            episode.rejection_reason = rejection_reason
            episode.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            try:
                send_content_rejected_email(
                    email=episode.creator.email,
                    rejection_reason=rejection_reason,
                    episode_name=episode.title,
                    creator_name=creator_display_name(episode.creator),
                    episode_id=str(episode.id),
                )
            except Exception:
                logger.error(
                    "Failed to send rejection email for episode %s",
                    episode_id,
                    exc_info=True,
                )  # noqa: E501
                pass

            try:
                NotificationService().send_push_for_event(
                    admin_user=episode.creator,
                    event_type="episode_rejected",
                    title="Episode Rejected",
                    body=f"'{episode.title}' review: {(rejection_reason or '')[:100]}",
                    data={
                        "type": "episode_rejected",
                        "episode_id": str(episode.id),
                        "reason": (rejection_reason or "")[:200],
                    },
                )
                NotificationService().create_notification(
                    admin_user=episode.creator,
                    type="episode_rejected",
                    title="Episode Rejected",
                    body=f"'{episode.title}' review: {(rejection_reason or '')[:100]}",
                    data={
                        "episode_id": str(episode.id),
                        "reason": (rejection_reason or "")[:200],
                    },
                )
            except Exception:
                logger.warning("Push for episode rejected failed (non-fatal)")
        else:
            raise ValidationError({"action": "Invalid action."})

        action_type = (
            ActivityLog.ActionType.VERIFICATION_APPROVED
            if episode.status == Episode.Status.PUBLISHED
            else ActivityLog.ActionType.VERIFICATION_REJECTED
        )
        decision = (
            "approved" if episode.status == Episode.Status.PUBLISHED else "rejected"
        )
        ActivityService.log_activity(
            action_type=action_type,
            description=f"{episode.creator.email} creator content was {decision}.",
            actor=admin,
            subject=episode.creator,
            metadata={
                "episode_id": str(episode.id),
                "episode_title": episode.title,
                "new_status": episode.status,
                "rejection_reason": episode.rejection_reason,
            },
        )
        return episode

    def get_verification_stats(self, admin: AdminUser) -> dict:
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied(
                "You do not have permission to view verification stats."
            )
        return self.content_repo.get_verification_stats(admin)

    def bulk_review_episodes(
        self,
        admin: AdminUser,
        episode_ids: list,
        action: str,
        rejection_reason: str = None,
    ) -> dict:
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied(
                "You do not have permission to bulk review episodes."
            )

        episodes = self.content_repo.get_episodes_for_bulk_review(episode_ids)

        found_ids = {str(e.id) for e in episodes}
        missing = [eid for eid in episode_ids if eid not in found_ids]

        results = {"processed": [], "skipped": missing}
        for episode in episodes:
            episode.status = (
                Episode.Status.PUBLISHED
                if action == "approve"
                else Episode.Status.REJECTED
            )
            episode.reviewed_by = admin
            episode.reviewed_at = timezone.now()
            if action == "reject" and rejection_reason:
                episode.rejection_reason = rejection_reason
            episode.save(
                update_fields=[
                    "status",
                    "reviewed_by",
                    "reviewed_at",
                    "rejection_reason",
                    "updated_at",
                ]
            )
            results["processed"].append(str(episode.id))
            if action == "approve":
                from skiflux.services.season_publish_service import (
                    SeasonPublishService,
                )

                SeasonPublishService().maybe_publish_season_for_episode(episode)

        if results["processed"]:
            ActivityService.log_activity(
                action_type=(
                    ActivityLog.ActionType.VERIFICATION_APPROVED
                    if action == "approve"
                    else ActivityLog.ActionType.VERIFICATION_REJECTED
                ),
                description=(
                    f"{len(results['processed'])} episodes were bulk {action}d."
                ),
                actor=admin,
                metadata={
                    "episode_ids": results["processed"],
                    "skipped_episode_ids": results["skipped"],
                    "action": action,
                    "rejection_reason": rejection_reason,
                },
            )

        return results

    def get_verification_queue(
        self,
        admin: AdminUser,
        priority: str = None,
        creator_id: uuid.UUID | str = None,
    ):
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied(
                "You do not have permission to view the verification queue."
            )

        queryset, sla_cutoff = self.content_repo.get_verification_queue(
            priority=priority, creator_id=creator_id
        )

        now = timezone.now()
        sla_hours = SystemContentConfig.get_config().sla_review_hours
        results = []
        for episode in queryset:
            results.append(
                {
                    "id": episode.id,
                    "title": episode.title,
                    "season_title": episode.season.title,
                    "season_skillworld": episode.season.skillworld,
                    "creator_name": (
                        f"{episode.creator.first_name} {episode.creator.last_name}"
                    ).strip(),
                    "creator_avatar_url": get_private_avatar_url(
                        episode.creator.avatar_public_id
                    ),
                    "submitted_at": episode.submitted_for_review_at,
                    "sla_deadline": episode.submitted_for_review_at
                    + timedelta(hours=sla_hours),
                    "sla_breached": episode.submitted_for_review_at <= sla_cutoff,
                    "priority": compute_priority(
                        episode.submitted_for_review_at, now, sla_hours
                    ),
                    "status": episode.status,
                }
            )
        return results

    def get_content_approval_stats(self, admin: AdminUser) -> dict:
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied("You do not have permission to view approval stats.")
        return self.content_repo.get_content_approval_stats()

    def get_content_approval_list(
        self,
        admin: AdminUser,
        status_filter: str = None,
        skillworld: str = None,
    ):
        if not admin.has_permission(Permission.CONTENT_MANAGE):
            raise PermissionDenied("You do not have permission to view approval list.")
        return self.content_repo.get_content_approval_list(
            status_filter=status_filter, skillworld=skillworld
        )

    def get_season_stats(self, season_id: str, admin: AdminUser) -> dict:
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError("Season not found.")
        if season.creator_id != admin.id and not self._can_view_content(admin):
            raise PermissionDenied(
                "You do not own this season or have permission to view season stats."
            )
        return self.content_repo.get_season_stats(season_id)

    def get_episodes_by_season(self, season_id: str, admin: AdminUser):
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError("Season not found.")

        if season.creator_id != admin.id and not self._can_view_content(admin):
            raise PermissionDenied(
                "You do not own this season or have permission to view season stats."
            )
        return self.content_repo.get_episodes_by_season(season_id)

    def get_episode_review_detail(self, episode_id: str, admin: AdminUser) -> dict:
        episode = self.content_repo.get_episode(episode_id)
        if not episode:
            raise ValidationError("Episode not found.")
        if episode.creator_id != admin.id and not self._can_view_content(admin):
            raise PermissionDenied(
                "You do not own this episode or have permission to view it."
            )

        tasks = episode.tasks.prefetch_related("questions").all()
        task_submissions = self.content_repo.get_task_submissions_by_episode(
            episode
        ).select_related("reviewed_by", "task__episode__season")
        comments = self.content_repo.get_comments(episode).order_by("-created_at")
        return {
            "episode": episode,
            "tasks": tasks,
            "task_submissions": task_submissions,
            "comments": comments,
        }

    def get_tasks_by_season(
        self,
        season_id: str,
        admin: AdminUser,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError("Season not found.")
        if season.creator_id != admin.id and not self._can_view_content(admin):
            raise PermissionDenied(
                "You do not own this season or have permission to view its tasks."
            )

        qs = self.content_repo.get_season_tasks_with_stats(season)
        total_count = qs.count()
        tasks = qs[offset : offset + limit]

        return {
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "results": [
                {
                    "id": str(task.id),
                    "episode_id": str(task.episode_id),
                    "episode_title": task.episode.title,
                    "episode_order": task.episode.order,
                    "kind": task.kind,
                    "sla_time_limit_hours": task.sla_time_limit_hours,
                    "task_brief": task.task_brief,
                    "accepted_proof_types": task.accepted_proof_types,
                    "pass_score_percent": task.pass_score_percent,
                    "time_limit_minutes": task.time_limit_minutes,
                    "max_attempts": task.max_attempts,
                    "completion_criteria": task.completion_criteria,
                    "total_submissions": (
                        task.total_project_submissions
                        + task.total_assessment_submissions
                    ),
                    "pending_submissions": task.pending_project_submissions,
                    "created_at": task.created_at,
                }
                for task in tasks
            ],
        }

    def get_comments_by_season(
        self,
        season_id: str,
        admin: AdminUser,
        flagged: bool = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        season = self.content_repo.get_season_by_id(season_id)
        if not season:
            raise ValidationError("Season not found.")
        if season.creator_id != admin.id and not self._can_view_content(admin):
            raise PermissionDenied(
                "You do not own this season or have permission to view its comments."
            )

        qs = self.content_repo.get_season_comments(season, flagged=flagged)
        total_count = qs.count()
        comments = qs[offset : offset + limit]

        return {
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "results": [
                {
                    "id": str(comment.id),
                    "user_id": str(comment.user.id),
                    "user_email": comment.user.email,
                    "user_name": (
                        f"{comment.user.first_name} {comment.user.last_name}"
                    ).strip(),
                    "user_avatar_url": comment.user.avatar_url,
                    "episode_id": str(comment.episode_id),
                    "episode_title": comment.episode.title,
                    "text": comment.text,
                    "flagged": comment.flagged,
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
                for comment in comments
            ],
        }
