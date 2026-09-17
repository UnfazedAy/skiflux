from rest_framework.permissions import BasePermission

from skiflux.models import AdminUser, Permission


class IsSuperAdmin(BasePermission):
    message = "Only super admins can perform this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated or not isinstance(user, AdminUser):
            return False
        return user.is_super_admin


class IsVerifiedCreator(BasePermission):
    message = "Complete Your Creator Profile (username and bio) before proceeding."

    SETUP_ACTIONS = {"update_profile"}

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "role_type", None) == AdminUser.RoleType.SUPER_ADMIN:
            return True

        if not getattr(user, "can_use_studio", False):
            return False

        if not getattr(user, "is_verified", False):
            return False

        # Allow access to setup actions before profile is complete
        if getattr(view, "action", None) in self.SETUP_ACTIONS:
            return True

        if not getattr(user, "username", None) or not getattr(user, "bio", None):
            return False

        return True


class HasCreatorViewPermission(BasePermission):
    message = "You do not have permission to view creators."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if (
            not user
            or not user.is_authenticated
            or not isinstance(
                user,
                AdminUser,
            )
        ):
            return False
        return user.has_permission(Permission.CREATOR_VIEW)


class HasCreatorManagePermission(BasePermission):
    message = "You do not have permission to manage creators."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if (
            not user
            or not user.is_authenticated
            or not isinstance(
                user,
                AdminUser,
            )
        ):
            return False
        return user.has_permission(Permission.CREATOR_MANAGE)


class HasEconomyViewPermission(BasePermission):
    message = (
        "You do not have administrative permission "
        "to view financial ledger transactions."
    )

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated or not isinstance(user, AdminUser):
            return False
        return user.has_permission(Permission.ECONOMY_VIEW)


class HasEconomyManagePermission(BasePermission):
    message = (
        "You do not have administrative permission to perform economy modifications."
    )

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated or not isinstance(user, AdminUser):
            return False
        return user.has_permission(Permission.ECONOMY_MANAGE)
