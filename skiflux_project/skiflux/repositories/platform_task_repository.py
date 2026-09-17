from typing import List, Optional

from django.db.models import Q
from django.utils import timezone

from skiflux.models.gamification import PlatformTask, UserPlatformTask
from skiflux.models.user import User


class PlatformTaskRepository:
    def get_task_by_id(self, task_id: str) -> Optional[PlatformTask]:
        try:
            return PlatformTask.objects.get(id=task_id)
        except PlatformTask.DoesNotExist:
            return None

    def get_task_by_slug(self, slug: str) -> Optional[PlatformTask]:
        try:
            return PlatformTask.objects.get(slug=slug)
        except PlatformTask.DoesNotExist:
            return None

    def get_tasks_by_trigger(self, trigger_type: str) -> List[PlatformTask]:
        if not trigger_type:
            return []
        return list(
            PlatformTask.objects.filter(
                trigger_type=trigger_type,
                is_active=True,
            ).order_by("sort_order", "title")
        )

    def get_active_tasks(self) -> List[PlatformTask]:
        return list(
            PlatformTask.objects.filter(is_active=True).order_by("sort_order", "title")
        )

    def list_tasks(
        self,
        *,
        is_active: bool | None = None,
        category: str | None = None,
        search: str | None = None,
    ) -> List[PlatformTask]:
        qs = PlatformTask.objects.all().order_by("sort_order", "title")
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        if category:
            qs = qs.filter(category=category)
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(slug__icontains=search)
            )
        return list(qs)

    def create_task(self, **data) -> PlatformTask:
        return PlatformTask.objects.create(**data)

    def update_task(self, task: PlatformTask, **data) -> PlatformTask:
        for field, value in data.items():
            setattr(task, field, value)
        task.save()
        return task

    def delete_task(self, task: PlatformTask) -> None:
        task.delete()

    def get_or_create_user_task(
        self,
        user: User,
        task: PlatformTask,
    ) -> tuple[UserPlatformTask, bool]:
        return UserPlatformTask.objects.get_or_create(
            user=user,
            platform_task=task,
            defaults={"status": UserPlatformTask.Status.NOT_STARTED},
        )

    def get_user_task(
        self,
        user: User,
        task: PlatformTask,
    ) -> Optional[UserPlatformTask]:
        return UserPlatformTask.objects.filter(user=user, platform_task=task).first()

    def get_user_tasks(self, user: User) -> List[UserPlatformTask]:
        return list(
            UserPlatformTask.objects.filter(user=user).select_related("platform_task")
        )

    def mark_started(self, user_task: UserPlatformTask) -> UserPlatformTask:
        if user_task.status == UserPlatformTask.Status.NOT_STARTED:
            user_task.status = UserPlatformTask.Status.IN_PROGRESS
            user_task.started_at = timezone.now()
            user_task.save(update_fields=["status", "started_at"])
        return user_task

    def mark_claimable(self, user_task: UserPlatformTask) -> UserPlatformTask:
        user_task.status = UserPlatformTask.Status.CLAIMABLE
        user_task.claimable_at = timezone.now()
        user_task.save(update_fields=["status", "claimable_at"])
        return user_task

    def mark_claimed(self, user_task: UserPlatformTask) -> UserPlatformTask:
        user_task.status = UserPlatformTask.Status.CLAIMED
        user_task.claimed_at = timezone.now()
        user_task.save(update_fields=["status", "claimed_at"])
        return user_task

    def increment_progress(
        self,
        user_task: UserPlatformTask,
        *,
        amount: int = 1,
        target: int,
    ) -> UserPlatformTask:
        user_task.progress_current = min(
            user_task.progress_current + amount,
            target,
        )
        update_fields = ["progress_current"]
        if user_task.progress_current >= target:
            user_task.status = UserPlatformTask.Status.CLAIMABLE
            user_task.claimable_at = timezone.now()
            update_fields.extend(["status", "claimable_at"])
        elif user_task.status == UserPlatformTask.Status.NOT_STARTED:
            user_task.status = UserPlatformTask.Status.IN_PROGRESS
            user_task.started_at = timezone.now()
            update_fields.extend(["status", "started_at"])
        user_task.save(update_fields=update_fields)
        return user_task
