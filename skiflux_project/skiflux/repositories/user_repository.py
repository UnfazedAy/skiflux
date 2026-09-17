from datetime import timedelta
from typing import Optional

from django.db.models import (
    Count,
    DecimalField,
    F,
    Value,
    Window,
    Q,
)
from django.db.models.functions import (
    Coalesce,
    DenseRank,
)
from django.utils import timezone

from skiflux.models import User


class UserRepository:
    def get_by_id(self, user_id: str) -> Optional[User]:
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    def get_for_update_by_pk(self, pk: str) -> User:
        return User.objects.select_for_update().get(pk=pk)

    def get_by_email(self, email: str) -> Optional[User]:
        try:
            return User.objects.get(email=email.lower().strip())
        except User.DoesNotExist:
            return None

    def get_by_username(self, username: str) -> Optional[User]:
        try:
            return User.objects.get(username__iexact=username.lower().strip())
        except User.DoesNotExist:
            return None

    def create(self, **kwargs) -> User:
        if "email" in kwargs:
            kwargs["email"] = kwargs["email"].lower().strip()

        password = kwargs.pop("password", None)
        user = User(**kwargs)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save()
        return user

    def update(self, user: User, **kwargs) -> User:
        for key, value in kwargs.items():
            setattr(user, key, value)
        user.save()
        return user

    def get_by_username_exclude(self, username: str, exclude_id) -> User | None:
        try:
            return User.objects.exclude(id=exclude_id).get(
                username__iexact=username.lower().strip()
            )
        except User.DoesNotExist:
            return None

    def get_by_phone_exclude(self, phone: str, exclude_id) -> User | None:
        try:
            return User.objects.exclude(id=exclude_id).get(phone=phone)
        except User.DoesNotExist:
            return None

    def get_learner_user_queryset(self):
        return (
            User.objects.filter(
                is_staff=False,
                is_superuser=False,
            )
            .annotate(
                project_tasks_done=Count("task_submissions", distinct=True),
                assessment_tasks_done=Count("assessment_submissions", distinct=True),
            )
            .annotate(tasks_done=F("project_tasks_done") + F("assessment_tasks_done"))
            .annotate(
                episode_completed_count=Count(
                    "viewed_episodes",
                    distinct=True,
                    filter=Q(viewed_episodes__completed=True),
                )
            )
            .annotate(
                coins=Coalesce(
                    F("wallet__balance"),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .annotate(
                rank=Window(
                    expression=DenseRank(),
                    partition_by=[F("current_level")],
                    order_by=[
                        F("xp").desc(),
                        F("created_at").asc(),
                    ],
                )
            )
        )

    def get_learner_stats(self) -> dict:
        qs = User.objects.filter(is_staff=False, is_superuser=False)
        total_users = qs.count()
        active_users = qs.filter(status="active").count()
        suspended_users = qs.filter(status="suspended").count()
        deactivated_users = qs.filter(status="deactivated").count()

        one_week_ago = timezone.now() - timedelta(days=7)
        new_this_week = qs.filter(created_at__gte=one_week_ago).count()

        return {
            "total_users": total_users,
            "active_users": active_users,
            "suspended_users": suspended_users,
            "deactivated_users": deactivated_users,
            "new_this_week": new_this_week,
        }

    def suspend(self, user: User) -> User:
        user.status = User.Status.SUSPENDED
        user.is_active = False
        user.save(update_fields=["status", "is_active", "updated_at"])
        return user

    def reactivate_user(self, user: User) -> User:
        user.status = User.Status.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active", "updated_at"])
        return user

    @staticmethod
    def deactivate_user(user: User) -> dict:
        user.is_active = False
        user.status = User.Status.DEACTIVATED
        user.save(update_fields=["is_active", "status"])
        return {"detail": "User deactivated."}
