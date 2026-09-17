import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.db import connection, models
from django.db.models import Q

from .role import Permission, Role
from .user import User


class AdminUserManager(models.Manager):
    """Custom manager with convenience factory methods."""

    def create_admin(
        self,
        email: str,
        first_name: str,
        password: str,
        **extra_fields,
    ):
        if not email:
            raise ValueError("Email is required.")
        extra_fields.setdefault("role_type", AdminUser.RoleType.ADMIN)
        if "role_types" not in extra_fields:
            extra_fields["role_types"] = [extra_fields["role_type"]]
        extra_fields.setdefault("is_verified", True)
        roles = extra_fields.pop("roles", None)
        admin = self.model(
            email=email.lower().strip(),
            first_name=first_name,
            **extra_fields,
        )
        admin.set_password(password)
        admin.save(using=self._db)
        if roles is not None:
            admin.roles.set(roles)
        return admin

    def create_super_admin(
        self,
        email: str,
        first_name: str,
        password: str,
        **extra_fields,
    ):
        extra_fields["role_type"] = AdminUser.RoleType.SUPER_ADMIN
        extra_fields["is_verified"] = True
        return self.create_admin(email, first_name, password, **extra_fields)


class AdminUser(models.Model):
    class RoleType(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        ADMIN = "admin", "Admin"
        CREATOR = "creator", "Creator"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DEACTIVATED = "deactivated", "Deactivated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(unique=True)

    password = models.CharField(max_length=255)
    username = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
    )
    avatar_public_id = models.CharField(max_length=255, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    display_name = models.CharField(max_length=255, blank=True, null=True)

    skillworld = models.CharField(
        max_length=50,
        choices=User.Skillworld.choices,
        null=True,
        blank=True,
    )

    role_type = models.CharField(
        max_length=20,
        choices=RoleType.choices,
        default=RoleType.ADMIN,
        help_text="Primary portal identity (admin, super_admin, "
        "or standalone creator).",
    )

    role_types = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Built-in role types held by this account. Platform admins may include "
            "'creator' here without changing role_type from 'admin'."
        ),
    )

    roles = models.ManyToManyField(
        Role,
        related_name="admin_users",
        blank=True,
        help_text="Custom and built-in roles assigned to this account.",
    )

    created_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_admins",
        help_text="The super admin who created this account.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    is_verified = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    last_failed_login = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AdminUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        verbose_name = "Admin User"
        verbose_name_plural = "Admin Users"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["email"], name="idx_admin_user_email"),
            models.Index(
                fields=["role_type"],
                name="idx_admin_user_role_type",
            ),
        ]

    def set_password(self, raw_password: str) -> None:
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    def wallet_lookup_kwargs(self) -> dict:
        return {"admin_user": self}

    @property
    def is_super_admin(self) -> bool:
        return self.role_type == self.RoleType.SUPER_ADMIN

    @classmethod
    def assignable_builtin_role_types(cls) -> tuple:
        return (cls.RoleType.ADMIN, cls.RoleType.CREATOR)

    @classmethod
    def creators_filter(cls) -> Q:
        creator = cls.RoleType.CREATOR
        q = Q(role_type=creator)

        if connection.vendor == "postgresql":
            q |= Q(role_types__contains=[creator])
        else:
            # SQLite (and other DBs without proper JSON contains support):
            # Fall back to a text search inside the JSON. This is safe and
            # sufficient for the simple list-of-strings use case we have.
            q |= Q(role_types__icontains=f'"{creator}"')

        return q

    def effective_role_types(self) -> list:
        if self.role_types:
            return list(self.role_types)
        return [self.role_type]

    def has_role_type(self, role_type: str) -> bool:
        return role_type in self.effective_role_types()

    def add_role_type(self, role_type: str) -> None:
        types = self.effective_role_types()
        if role_type not in types:
            types.append(role_type)
        self.role_types = types

    def remove_role_type(self, role_type: str) -> None:
        types = [t for t in self.effective_role_types() if t != role_type]
        self.role_types = types

    def _assigned_roles(self):
        if hasattr(self, "_prefetched_objects_cache") and "roles" in (
            self._prefetched_objects_cache
        ):
            return list(self.roles.all())
        return list(self.roles.all())

    @property
    def can_use_studio(self) -> bool:
        if self.is_super_admin:
            return True
        return self.has_role_type(self.RoleType.CREATOR)

    @property
    def is_listed_creator(self) -> bool:
        return self.has_role_type(self.RoleType.CREATOR)

    @property
    def has_portal_roles(self) -> bool:
        return any(r.permissions for r in self._assigned_roles())

    def has_permission(self, codename: str) -> bool:
        if self.is_super_admin:
            return True
        return any(r.has_permission(codename) for r in self._assigned_roles())

    def get_all_permissions(self) -> list:
        if self.is_super_admin:
            return list(Permission.ALL)
        merged = set()
        for role in self._assigned_roles():
            merged.update(role.permissions or [])
        return sorted(merged)

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def is_authenticated(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} <{self.email}> [{self.role_type}]"
