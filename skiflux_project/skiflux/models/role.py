import uuid

from django.db import models


class Permission:
    USERS_VIEW = "users.view"
    USERS_EDIT = "users.edit"
    USERS_DELETE = "users.delete"
    USERS_SUSPEND = "users.suspend"

    ROLES_VIEW = "roles.view"
    ROLES_MANAGE = "roles.manage"

    CONTENT_VIEW = "content.view"
    CONTENT_MANAGE = "content.manage"

    ECONOMY_VIEW = "economy.view"
    ECONOMY_MANAGE = "economy.manage"

    ANALYTICS_VIEW = "analytics.view"

    ADMIN_USERS_VIEW = "admin_users.view"
    ADMIN_USERS_MANAGE = "admin_users.manage"

    CREATOR_VIEW = "creator.view"
    CREATOR_MANAGE = "creator.manage"

    MODERATION_VIEW = "moderation.view"
    MODERATION_MANAGE = "moderation.manage"

    SUPPORT_VIEW = "support.view"
    SUPPORT_MANAGE = "support.manage"
    SUPPORT_ASSIGN = "support.assign"

    ALL = [
        USERS_VIEW,
        USERS_EDIT,
        USERS_DELETE,
        USERS_SUSPEND,
        ROLES_VIEW,
        ROLES_MANAGE,
        CONTENT_VIEW,
        CONTENT_MANAGE,
        ECONOMY_VIEW,
        ECONOMY_MANAGE,
        ANALYTICS_VIEW,
        ADMIN_USERS_VIEW,
        ADMIN_USERS_MANAGE,
        CREATOR_VIEW,
        CREATOR_MANAGE,
        MODERATION_VIEW,
        MODERATION_MANAGE,
        SUPPORT_VIEW,
        SUPPORT_MANAGE,
        SUPPORT_ASSIGN,
    ]


class Role(models.Model):
    CREATOR_STUDIO_ROLE_NAME = "Creator"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    permissions = models.JSONField(
        default=list,
        help_text="List of Permission codenames granted to this role.",
    )

    is_custom = models.BooleanField(
        default=True,
        help_text="False for built-in system roles; True for super-admin-created roles.",  # noqa: E501
    )

    grants_studio_access = models.BooleanField(
        default=False,
        help_text="When True, holders of this role may use the creator studio.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Role"
        verbose_name_plural = "Roles"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def has_permission(self, codename: str) -> bool:
        """Return True when this role explicitly includes the given permission."""
        return codename in (self.permissions or [])

    @classmethod
    def get_or_create_creator_studio_role(cls) -> "Role":
        role, created = cls.objects.get_or_create(
            name=cls.CREATOR_STUDIO_ROLE_NAME,
            defaults={
                "description": "Built-in studio access for "
                "uploading and managing content.",
                "permissions": [],
                "is_custom": False,
                "grants_studio_access": True,
            },
        )
        if not role.grants_studio_access:
            role.grants_studio_access = True
            role.save(update_fields=["grants_studio_access", "updated_at"])
        return role
