from typing import Optional

from django.db.models import Prefetch, Q

from skiflux.models import AdminUser, Role


class AdminUserRepository:
    _roles_prefetch = Prefetch("roles", queryset=Role.objects.all())

    def get_by_id(self, admin_id: str) -> Optional[AdminUser]:
        try:
            return (
                AdminUser.objects.select_related("created_by")
                .prefetch_related(self._roles_prefetch)
                .get(id=admin_id)
            )
        except AdminUser.DoesNotExist:
            return None

    def get_by_email(self, email: str) -> Optional[AdminUser]:
        try:
            return AdminUser.objects.prefetch_related(self._roles_prefetch).get(
                email=email.lower().strip()
            )
        except AdminUser.DoesNotExist:
            return None

    def get_by_username(self, username: str) -> Optional[AdminUser]:
        try:
            return AdminUser.objects.prefetch_related(self._roles_prefetch).get(
                username=username.lower().strip()
            )
        except AdminUser.DoesNotExist:
            return None

    def create(
        self,
        email: str,
        first_name: str,
        password: str,
        role_type: str,
        role_types: Optional[list] = None,
        username: Optional[str] = None,
        avatar_public_id: Optional[str] = None,
        bio: Optional[str] = None,
        last_name: str = "",
        roles: Optional[list] = None,
        created_by: Optional[AdminUser] = None,
        is_active: bool = True,
    ) -> AdminUser:
        admin = AdminUser(
            email=email.lower().strip(),
            first_name=first_name,
            last_name=last_name,
            role_type=role_type,
            role_types=role_types if role_types is not None else [role_type],
            created_by=created_by,
            username=username,
            avatar_public_id=avatar_public_id,
            bio=bio,
            is_active=is_active,
        )
        admin.set_password(password)
        admin.save()
        if roles:
            admin.roles.set(roles)
        return admin

    def update(self, admin: AdminUser, **kwargs) -> AdminUser:
        for key, value in kwargs.items():
            setattr(admin, key, value)
        admin.save()
        return admin

    def list_all(self) -> list:
        return list(
            AdminUser.objects.select_related("created_by")
            .prefetch_related(self._roles_prefetch)
            .order_by("created_at")
        )

    def list_by_role_type(self, role_type: str) -> list:
        return list(
            AdminUser.objects.filter(role_type=role_type)
            .select_related("created_by")
            .prefetch_related(self._roles_prefetch)
            .order_by("created_at")
        )

    def list_creators(self) -> list:
        return list(
            AdminUser.objects.filter(
                AdminUser.creators_filter(),
                is_active=True,
            )
            .select_related("created_by")
            .prefetch_related(self._roles_prefetch)
            .order_by("created_at")
        )

    def list_all_queryset(
        self, role_name: Optional[str] = None, role_type: Optional[str] = None
    ):
        """Returns a queryset of all admins, optionally filtered by role name."""
        qs = AdminUser.objects.select_related("created_by").prefetch_related(
            self._roles_prefetch
        )
        if role_name:
            # Filter by custom role name
            qs = qs.filter(roles__name__iexact=role_name).distinct()
        if role_type:
            normalized = role_type.strip().lower()
            candidates = qs.filter(
                Q(role_types__icontains=normalized) | Q(roles__name__iexact=role_type)
            ).distinct()

            matching_ids = [
                admin.id
                for admin in candidates
                if normalized in [r.lower() for r in (admin.role_types or [])]
                or any(r.name.lower() == normalized for r in admin.roles.all())
            ]
            qs = qs.filter(id__in=matching_ids)
        return qs.order_by("created_at")

    def deactivate(self, admin: AdminUser) -> AdminUser:
        admin.status = AdminUser.Status.DEACTIVATED
        admin.is_active = False
        admin.save(
            update_fields=[
                "is_active",
                "updated_at",
                "status",
            ]
        )
        return admin

    def suspend(self, admin: AdminUser) -> AdminUser:
        admin.status = AdminUser.Status.SUSPENDED
        admin.is_active = False
        admin.save(
            update_fields=[
                "is_active",
                "updated_at",
                "status",
            ]
        )
        return admin

    def reactivate(self, admin: AdminUser) -> AdminUser:
        admin.status = AdminUser.Status.ACTIVE
        admin.is_active = True
        admin.save(
            update_fields=[
                "is_active",
                "updated_at",
                "status",
            ]
        )
        return admin
