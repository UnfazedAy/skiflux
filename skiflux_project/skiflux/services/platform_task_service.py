from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from skiflux.models.gamification import PlatformTask, UserPlatformTask
from skiflux.models.user import User
from skiflux.models.wallet import PaymentTransaction, SkillcoinTransaction
from skiflux.repositories.platform_task_repository import PlatformTaskRepository
from skiflux.services.gamification_service import GamificationService
from skiflux.services.wallet_service import WalletService


class PlatformTaskService:
    def __init__(self):
        self.task_repo = PlatformTaskRepository()
        self.gamification_service = GamificationService()
        self.wallet_service = WalletService()

    def get_tasks_with_status(self, user: User) -> List[dict]:
        active_tasks = self.task_repo.get_active_tasks()
        user_tasks = {
            ut.platform_task_id: ut for ut in self.task_repo.get_user_tasks(user)
        }
        results = []
        for task in active_tasks:
            user_task = user_tasks.get(task.id)
            results.append(self._serialize_task_for_user(task, user_task))
        return results

    def list_admin_tasks(
        self,
        *,
        is_active: bool | None = None,
        category: str | None = None,
        search: str | None = None,
    ) -> List[PlatformTask]:
        return self.task_repo.list_tasks(
            is_active=is_active,
            category=category,
            search=search,
        )

    def get_admin_task(self, task_id: str) -> PlatformTask:
        task = self.task_repo.get_task_by_id(task_id)
        if not task:
            raise ValidationError("Platform task not found.")
        return task

    @transaction.atomic
    def create_task(self, data: dict) -> PlatformTask:
        payload = self._normalize_admin_payload(data)
        slug = payload.get("slug") or self._generate_unique_slug(payload["title"])
        if self.task_repo.get_task_by_slug(slug):
            raise ValidationError({"slug": "This slug is already in use."})
        payload["slug"] = slug
        payload.setdefault(
            "verification_mode",
            PlatformTask.VerificationMode.MANUAL
            if not payload.get("trigger_type")
            else PlatformTask.VerificationMode.AUTOMATIC,
        )
        return self.task_repo.create_task(**payload)

    @transaction.atomic
    def update_task(self, task_id: str, data: dict) -> PlatformTask:
        task = self.get_admin_task(task_id)
        payload = self._normalize_admin_payload(data, partial=True)
        if "slug" in payload and payload["slug"] != task.slug:
            existing = self.task_repo.get_task_by_slug(payload["slug"])
            if existing and existing.id != task.id:
                raise ValidationError({"slug": "This slug is already in use."})
        return self.task_repo.update_task(task, **payload)

    def deactivate_task(self, task_id: str) -> PlatformTask:
        task = self.get_admin_task(task_id)
        return self.task_repo.update_task(task, is_active=False)

    @transaction.atomic
    def start_task(self, user: User, task_id: str) -> dict:
        task = self._get_active_task(task_id)
        user_task, _ = self.task_repo.get_or_create_user_task(user, task)
        if user_task.status == UserPlatformTask.Status.CLAIMED:
            raise ValidationError("Platform task already claimed.")

        user_task = self.task_repo.mark_started(user_task)
        return self._serialize_task_for_user(task, user_task)

    @transaction.atomic
    def submit_task(self, user: User, task_id: str) -> dict:
        """Manual tasks: user confirms they completed the required action."""
        task = self._get_active_task(task_id)
        if task.verification_mode != PlatformTask.VerificationMode.MANUAL:
            raise ValidationError("This task is tracked automatically.")

        user_task, _ = self.task_repo.get_or_create_user_task(user, task)
        if user_task.status == UserPlatformTask.Status.CLAIMED:
            raise ValidationError("Platform task already claimed.")
        if user_task.status == UserPlatformTask.Status.CLAIMABLE:
            return self._serialize_task_for_user(task, user_task)

        user_task.progress_current = task.progress_target
        user_task = self.task_repo.mark_claimable(user_task)
        user_task.save(update_fields=["progress_current"])
        return self._serialize_task_for_user(task, user_task)

    @transaction.atomic
    def claim_task(self, user: User, task_id: str) -> dict:
        task = self._get_active_task(task_id)
        user_task = self.task_repo.get_user_task(user, task)
        if not user_task or user_task.status != UserPlatformTask.Status.CLAIMABLE:
            raise ValidationError("Platform task is not ready to claim.")

        user_task = self.task_repo.mark_claimed(user_task)
        self._grant_rewards(user, task)
        return self._serialize_task_for_user(task, user_task)

    @transaction.atomic
    def complete_task(self, user: User, task_id: str) -> dict:
        """Backward-compatible endpoint: submit manual tasks, then claim."""
        task = self._get_active_task(task_id)
        user_task = self.task_repo.get_user_task(user, task)

        if user_task and user_task.status == UserPlatformTask.Status.CLAIMED:
            raise ValidationError("Platform task already completed.")

        if user_task and user_task.status == UserPlatformTask.Status.CLAIMABLE:
            return self.claim_task(user, task_id)

        if task.verification_mode == PlatformTask.VerificationMode.MANUAL:
            self.submit_task(user, task_id)
            return self.claim_task(user, task_id)

        raise ValidationError(
            "This task must be completed in the app before you can claim it."
        )

    @transaction.atomic
    def handle_trigger(
        self,
        user: User,
        trigger_type: str,
        *,
        increment: int = 1,
    ) -> None:
        if not trigger_type:
            return

        for task in self.task_repo.get_tasks_by_trigger(trigger_type):
            if not self._trigger_condition_met(user, task):
                continue

            user_task, _ = self.task_repo.get_or_create_user_task(user, task)
            if user_task.status == UserPlatformTask.Status.CLAIMED:
                continue
            if user_task.status == UserPlatformTask.Status.CLAIMABLE:
                continue

            self.task_repo.increment_progress(
                user_task,
                amount=increment,
                target=task.progress_target,
            )

    def _trigger_condition_met(self, user: User, task: PlatformTask) -> bool:
        if task.trigger_type == PlatformTask.TriggerType.COMPLETE_PROFILE:
            return self._is_profile_complete(user)
        if task.trigger_type == PlatformTask.TriggerType.LINK_SOCIAL:
            return self._is_social_linked(user)
        if task.trigger_type == PlatformTask.TriggerType.FIRST_DEPOSIT:
            return self._has_successful_deposit(user)
        if task.trigger_type == PlatformTask.TriggerType.REFER_FRIEND:
            return False
        return True

    @staticmethod
    def _is_profile_complete(user: User) -> bool:
        return bool(user.is_onboarded and user.username)

    @staticmethod
    def _is_social_linked(user: User) -> bool:
        return user.auth_provider != User.AuthProvider.EMAIL or bool(user.social_id)

    @staticmethod
    def _has_successful_deposit(user: User) -> bool:
        return PaymentTransaction.objects.filter(
            user=user,
            status=PaymentTransaction.Status.SUCCESSFUL,
        ).exists()

    def _grant_rewards(self, user: User, task: PlatformTask) -> None:
        if task.xp_reward > 0:
            self.gamification_service.add_xp(user, task.xp_reward)
        if task.skillcoin_reward > 0:
            self.wallet_service.credit_bonus_balance(
                user,
                task.skillcoin_reward,
                SkillcoinTransaction.Type.CASHBACK_REWARD,
                f"Platform Task Completed: {task.title}",
                idempotency_key=f"platform-task-{task.id}-{user.id}",
            )
        self.gamification_service.process_daily_activity(user)

    def _get_active_task(self, task_id: str) -> PlatformTask:
        task = self.task_repo.get_task_by_id(task_id)
        if not task or not task.is_active:
            raise ValidationError("Platform task not found or inactive.")
        return task

    def _serialize_task_for_user(
        self,
        task: PlatformTask,
        user_task: Optional[UserPlatformTask],
    ) -> dict:
        status = user_task.status if user_task else UserPlatformTask.Status.NOT_STARTED
        progress_current = user_task.progress_current if user_task else 0
        return {
            "id": str(task.id),
            "slug": task.slug,
            "title": task.title,
            "description": task.description,
            "category": task.category,
            "trigger_type": task.trigger_type,
            "action_type": task.trigger_type,
            "verification_mode": task.verification_mode,
            "progress_target": task.progress_target,
            "progress_current": progress_current,
            "duration_minutes": task.duration_minutes,
            "external_url": task.external_url or None,
            "icon": task.icon or None,
            "metadata": task.metadata or {},
            "sort_order": task.sort_order,
            "xp_reward": task.xp_reward,
            "skillcoin_reward": str(task.skillcoin_reward),
            "is_active": task.is_active,
            "status": status,
            "claimable": status == UserPlatformTask.Status.CLAIMABLE,
            "completed": status == UserPlatformTask.Status.CLAIMED,
            "started_at": user_task.started_at if user_task else None,
            "claimable_at": user_task.claimable_at if user_task else None,
            "claimed_at": user_task.claimed_at if user_task else None,
            "completed_at": user_task.claimed_at if user_task else None,
        }

    def _normalize_admin_payload(self, data: dict, *, partial: bool = False) -> dict:
        allowed = {
            "slug",
            "title",
            "description",
            "category",
            "trigger_type",
            "verification_mode",
            "progress_target",
            "duration_minutes",
            "external_url",
            "icon",
            "metadata",
            "sort_order",
            "xp_reward",
            "skillcoin_reward",
            "is_active",
        }
        payload = {key: data[key] for key in allowed if key in data}

        if "trigger_type" in payload and payload["trigger_type"] is None:
            payload["trigger_type"] = ""

        if "skillcoin_reward" in payload and payload["skillcoin_reward"] is not None:
            payload["skillcoin_reward"] = Decimal(str(payload["skillcoin_reward"]))

        if not partial and "title" not in payload:
            raise ValidationError({"title": "This field is required."})

        if "trigger_type" in payload and not payload["trigger_type"]:
            payload["verification_mode"] = PlatformTask.VerificationMode.MANUAL
        elif "trigger_type" in payload and payload["trigger_type"]:
            payload.setdefault(
                "verification_mode",
                PlatformTask.VerificationMode.AUTOMATIC,
            )

        return payload

    def _generate_unique_slug(self, title: str) -> str:
        base = slugify(title) or "platform-task"
        slug = base
        counter = 1
        while self.task_repo.get_task_by_slug(slug):
            slug = f"{base}-{counter}"
            counter += 1
        return slug
