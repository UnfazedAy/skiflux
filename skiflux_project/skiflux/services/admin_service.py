from datetime import datetime, timezone

from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from skiflux.models import ActivityLog, AdminUser, Permission, Role, User
from skiflux.models.moderation import ModerationActionLog
from skiflux.repositories import (
    AdminUserRepository,
    ContentRepository,
    CreatorRepository,
    UserRepository,
)
from skiflux.repositories.moderation_repository import ModerationRepository
from skiflux.repositories.role_repository import RoleRepository
from skiflux.services.activity import ActivityService
from skiflux.utils import (
    blacklist_token,
    consume_password_reset_otp,
    create_admin_access_token,
    create_admin_refresh_token,
    generate_otp,
    hash_password,
    password_generator,
    peek_password_reset_otp,
    refresh_admin_access_token,
    send_admin_invitation_email,
    send_reset_password_email,
    set_password_reset_otp,
)
from skiflux.utils.lockout import (
    is_account_locked,
    record_failed_login,
    reset_failed_login_attempts,
)


class AdminService:
    def __init__(self):
        self.repo = AdminUserRepository()
        self.user_repo = UserRepository()
        self.content_repo = ContentRepository()
        self.creator_repo = CreatorRepository()
        self.moderation_repo = ModerationRepository()
        self.role_repo = RoleRepository()

    def get_default_creator_role(self) -> list[Role]:
        """Fetch the built-in Creator studio role, creating it if it doesn't
        exist yet. Never raises — creator admins can be created even if this
        role is somehow unavailable, they'll just start with no roles."""
        return Role.get_or_create_creator_studio_role()

    @staticmethod
    def available_permissions() -> list:
        return [
            {
                "codename": p,
                "label": p.replace(".", " › ").replace("_", " ").title(),
            }
            for p in Permission.ALL
        ]

    @staticmethod
    def _validate_permissions(permissions: list) -> None:
        invalid = [p for p in permissions if p not in Permission.ALL]
        if invalid:
            raise ValidationError(
                {"permissions": f"Unknown permission codenames: {invalid}"}
            )

    @staticmethod
    def _serialize_roles(admin: AdminUser) -> list:
        return [
            {
                "id": str(role.id),
                "name": role.name,
                "permissions": role.permissions,
                "is_custom": role.is_custom,
                "grants_studio_access": role.grants_studio_access,
            }
            for role in admin.roles.all()
        ]

    @classmethod
    def serialize_admin(cls, admin: AdminUser) -> dict:
        return {
            "id": str(admin.id),
            "email": admin.email,
            "first_name": admin.first_name,
            "last_name": admin.last_name,
            "status": admin.status,
            "role_type": admin.role_type,
            "role_types": admin.effective_role_types(),
            "roles": cls._serialize_roles(admin),
            "permissions": admin.get_all_permissions(),
            "can_use_studio": admin.can_use_studio,
            "is_active": admin.is_active,
        }

    def login(self, email: str, password: str) -> dict:
        admin = self.repo.get_by_email(email)

        if admin and is_account_locked(admin.email):
            raise ValidationError(
                "Account temporarily locked due to too many failed attempts."
            )

        if not admin or not admin.check_password(password):
            if admin:
                record_failed_login(admin.email)
            else:
                check_password(password, "pbkdf2_sha256$600000$dummy$hash")
            raise ValidationError("Invalid credentials.")

        reset_failed_login_attempts(admin.email)

        if not admin.is_active:
            raise ValidationError("This admin account has been deactivated.")

        if not admin.is_verified:
            raise ValidationError("Please verify your email address before logging in.")

        admin.last_login = datetime.now(timezone.utc)
        admin.save(update_fields=["last_login"])

        return {
            "access_token": create_admin_access_token(admin.id),
            "refresh_token": create_admin_refresh_token(admin.id),
            "admin": self.serialize_admin(admin),
            "must_change_password": admin.must_change_password,
        }

    def token_refresh(self, refresh_token: str) -> dict:
        try:
            tokens = refresh_admin_access_token(refresh_token)
            return tokens
        except ValueError as e:
            raise ValueError(str(e))

    def logout(self, refresh_token: str) -> None:
        try:
            blacklist_token(refresh_token)
        except ValueError as e:
            raise ValueError(str(e))

    def forgot_password(self, email: str) -> None:
        admin = self.repo.get_by_email(email)
        if admin:
            otp = generate_otp()
            set_password_reset_otp(admin.email, otp)
            send_reset_password_email(admin.email, otp)

    def verify_password_otp(self, email: str, otp: str) -> None:
        try:
            is_valid = peek_password_reset_otp(email, otp)
        except ValueError as e:
            raise ValidationError(str(e))
        if not is_valid:
            raise ValidationError("Invalid or expired OTP.")

    def reset_password(self, email: str, otp: str, new_password: str) -> None:
        admin = self.repo.get_by_email(email)
        if not admin:
            raise ValidationError({"email": "Admin user does not exist."})

        try:
            validate_password(new_password, user=admin)
        except Exception as e:
            raise ValidationError({"new_password": list(e.messages)})

        # Check that new password is different from old one
        msg = "New password cannot be the same as the current password."
        if admin.check_password(new_password):
            raise ValidationError({"new_password": msg})

        try:
            is_valid = consume_password_reset_otp(email, otp)
        except ValueError as e:
            raise ValidationError(str(e))
        if not is_valid:
            raise ValidationError({"otp": "Invalid or expired OTP."})

        self.repo.update(admin, password=hash_password(new_password))

    def change_password(
        self, admin_id: str, current_password: str, new_password: str
    ) -> None:
        admin = self.repo.get_by_id(admin_id)
        if not admin:
            raise ValidationError({"admin_id": "Admin user does not exist."})

        if not admin.check_password(current_password):
            raise ValidationError(
                {"current_password": "Current password is incorrect."}
            )

        try:
            validate_password(new_password, user=admin)
        except Exception as e:
            raise ValidationError({"new_password": list(e.messages)})

        # Also make sure new password is different from old one
        msg = "New password cannot be the same as the current password."
        if admin.check_password(new_password):
            raise ValidationError({"new_password": msg})

        self.repo.update(admin, password=hash_password(new_password))
        # falsify must_change_password after successful password change
        if admin.must_change_password:
            self.repo.update(admin, must_change_password=False)

    def create_role(
        self, name: str, description: str = "", permissions: list = None
    ) -> Role:
        self._validate_permissions(permissions or [])
        role, err = self.role_repo.create(
            name=name,
            description=description,
            permissions=permissions or [],
            is_custom=True,
        )
        if err == "IntegrityError":
            raise ValidationError({"name": "A role with this name already exists."})
        return role

    def list_roles(self) -> list:
        return self.role_repo.get_all()

    def get_role(self, role_id: str) -> Role:
        role = self.role_repo.get_by_id(role_id)
        if not role:
            raise ValidationError("Role not found.")
        return role

    def update_role(self, role_id: str, **kwargs) -> Role:
        role = self.get_role(role_id)

        if "permissions" in kwargs:
            self._validate_permissions(kwargs["permissions"])

        if (
            "name" in kwargs
            and kwargs["name"] != role.name
            and self.role_repo.get_by_name(kwargs["name"])
        ):
            raise ValidationError({"name": "A role with this name already exists."})

        for key, value in kwargs.items():
            setattr(role, key, value)
        role.save()
        return role

    def delete_role(self, role_id: str) -> None:
        role = self.get_role(role_id)
        if not role.is_custom or role.name == Role.CREATOR_STUDIO_ROLE_NAME:
            raise ValidationError("Built-in system roles cannot be deleted.")
        if role.admin_users.exists():
            raise ValidationError(
                "Cannot delete a role that is currently assigned to admin users. "
                "Re-assign those users first."
            )
        role.delete()

    def create_admin_user(
        self,
        acting_admin: AdminUser,
        email: str,
        first_name: str,
        role_type: str,
        last_name: str = "",
        role_id: str = None,
    ) -> AdminUser:
        roles_to_assign = []
        if role_type == AdminUser.RoleType.ADMIN:
            if not role_id:
                raise ValidationError(
                    {"role_id": "A role must be assigned for non-super-admin users."}
                )
            roles_to_assign.append(self.get_role(role_id))

        elif role_type == AdminUser.RoleType.CREATOR:
            default_creator_role = self.get_default_creator_role()
            if default_creator_role:
                roles_to_assign.append(default_creator_role)

        try:
            temporary_password = password_generator.generate_temporary_password()
            admin = self.repo.create(
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=temporary_password,
                role_type=role_type,
                roles=roles_to_assign,
                created_by=acting_admin,
            )
            admin.is_verified = True
            admin.must_change_password = True
            admin.save(update_fields=["is_verified", "must_change_password"])
            send_admin_invitation_email(
                email=admin.email,
                full_name=f"{admin.first_name} {admin.last_name}".strip(),
                temporary_password=temporary_password,
            )
            ActivityService.log_activity(
                action_type=ActivityLog.ActionType.ADMIN_CREATED,
                description=f"{admin.email} admin account was created.",
                actor=acting_admin,
                subject=admin,
                metadata={
                    "admin_id": str(admin.id),
                    "role_type": admin.role_type,
                    "role_ids": [str(role.id) for role in roles_to_assign],
                },
            )
        except IntegrityError:
            raise ValidationError(
                {"email": "An admin user with this email already exists."}
            )
        return admin

    def assign_roles(
        self,
        acting_admin: AdminUser,
        admin_id: str,
        add_role_ids: list = None,
        remove_role_ids: list = None,
        add_role_types: list = None,
        remove_role_types: list = None,
    ) -> AdminUser:
        admin = self.get_admin_user(admin_id)

        if admin.is_super_admin:
            raise ValidationError("Super admin accounts do not use role assignments.")

        add_role_ids = add_role_ids or []
        remove_role_ids = remove_role_ids or []
        add_role_types = add_role_types or []
        remove_role_types = remove_role_types or []
        if (
            not add_role_ids
            and not remove_role_ids
            and not add_role_types
            and not remove_role_types
        ):
            raise ValidationError(
                "Provide at least one of add_role_ids, remove_role_ids, "
                "add_role_types, or remove_role_types."
            )

        assignable = set(AdminUser.assignable_builtin_role_types())
        for role_type in add_role_types + remove_role_types:
            if role_type not in assignable:
                raise ValidationError(
                    {
                        "role_types": (
                            f"Invalid built-in role type '{role_type}'. "
                            f"Allowed: {sorted(assignable)}."
                        )
                    }
                )
            if role_type == admin.role_type:
                raise ValidationError(
                    {
                        "role_types": (
                            f"Account primary role_type is already '{role_type}'."
                        )
                    }
                )

        for role_type in add_role_types:
            admin.add_role_type(role_type)

        for role_type in remove_role_types:
            if role_type == admin.role_type:
                raise ValidationError(
                    {
                        "remove_role_types": "Cannot remove the account primary role type."  # noqa: E501
                    }
                )
            admin.remove_role_type(role_type)

        if add_role_ids:
            roles = self.role_repo.filter_by_ids(add_role_ids)
            if len(roles) != len(set(add_role_ids)):
                raise ValidationError({"add_role_ids": "One or more roles not found."})
            for role in roles:
                if not role.is_custom:
                    raise ValidationError(
                        {
                            "add_role_ids": (
                                "Built-in role types must be assigned via "
                                "add_role_types, not add_role_ids."
                            )
                        }
                    )
                admin.roles.add(role)

        if remove_role_ids:
            roles = self.role_repo.filter_by_ids(remove_role_ids)
            if len(roles) != len(set(remove_role_ids)):
                raise ValidationError(
                    {"remove_role_ids": "One or more roles not found."}
                )
            for role in roles:
                if not role.is_custom:
                    raise ValidationError(
                        {
                            "remove_role_ids": (
                                "Built-in role types must be removed via "
                                "remove_role_types, not remove_role_ids."
                            )
                        }
                    )
                admin.roles.remove(role)

        if admin.role_type == AdminUser.RoleType.ADMIN and not admin.roles.exists():
            raise ValidationError(
                "Platform admin accounts must retain at least one custom portal role."
            )

        admin.save(update_fields=["role_types", "updated_at"])
        updated_admin = self.get_admin_user(admin_id)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.ADMIN_ROLE_CHANGED,
            description=f"{updated_admin.email} admin permissions were updated.",
            actor=acting_admin,
            subject=updated_admin,
            metadata={
                "admin_id": str(updated_admin.id),
                "added_role_ids": [str(role_id) for role_id in add_role_ids],
                "removed_role_ids": [str(role_id) for role_id in remove_role_ids],
                "added_role_types": add_role_types,
                "removed_role_types": remove_role_types,
            },
        )
        return updated_admin

    def list_admin_users(self) -> list:
        return self.repo.list_all()

    def get_learner_stats(self) -> dict:
        return self.user_repo.get_learner_stats()

    def list_learners(
        self,
        status: str = None,
        skillworld: str = None,
        search: str = "",
    ):
        qs = self.user_repo.get_learner_user_queryset()

        if status:
            valid_statuses = ["active", "suspended", "deactivated"]
            if status not in valid_statuses:
                raise ValueError(
                    f"Invalid status filter. Must be one of: {valid_statuses}"
                )
            qs = qs.filter(status=status)

        if skillworld:
            from django.db import connection

            if connection.vendor == "postgresql":
                qs = qs.filter(skillworld__contains=skillworld)
            else:
                qs = qs.filter(skillworld__icontains=f'"{skillworld}"')

        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        return qs.order_by("-created_at")

    def get_admin_user(self, admin_id: str) -> AdminUser:
        admin = self.repo.get_by_id(admin_id)
        if not admin:
            raise ValidationError("Admin user not found.")
        return admin

    def update_admin_user(
        self, acting_admin: AdminUser, admin_id: str, **kwargs
    ) -> AdminUser:
        admin = self.get_admin_user(admin_id)

        if admin.is_super_admin and not acting_admin.is_super_admin:
            raise ValidationError(
                "You do not have permission to modify a Super Admin account."
            )

        if "password" in kwargs:
            raw_password = kwargs.pop("password")
            admin.set_password(raw_password)
            admin.save(update_fields=["password"])

        return self.repo.update(admin, **kwargs)

    def deactivate_admin_user(
        self, acting_admin: AdminUser, admin_id: str
    ) -> AdminUser:
        admin = self.get_admin_user(admin_id)
        if admin.is_super_admin:
            raise ValidationError(
                "Super Admin accounts cannot be deactivated through the portal."
            )

        if str(admin.id) == str(acting_admin.id):
            raise ValidationError("You cannot deactivate your own account.")

        self.repo.deactivate(admin)
        cache.delete(f"auth_admin_{admin_id}")
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.ADMIN_DEACTIVATED,
            description=f"{admin.email} admin account was deactivated.",
            actor=acting_admin,
            subject=admin,
            metadata={"admin_id": str(admin.id)},
        )
        return admin

    def reactivate_admin_user(
        self, acting_admin: AdminUser, admin_id: str
    ) -> AdminUser:
        admin = self.get_admin_user(admin_id)
        if str(admin.id) == str(acting_admin.id):
            raise ValidationError("You cannot modify your own account status.")

        if admin.is_super_admin and not acting_admin.is_super_admin:
            raise ValidationError(
                "You do not have permission to reactivate a Super Admin account."
            )
        return self.repo.reactivate(admin)

    def suspend_admin_user(
        self, acting_admin: AdminUser, admin_id: str, reason: str = ""
    ) -> AdminUser:
        """Suspend an admin user (temporary restriction)."""
        admin = self.get_admin_user(admin_id)
        if admin.is_super_admin:
            raise ValidationError(
                "Super Admin accounts cannot be suspended through the portal."
            )

        if str(admin.id) == str(acting_admin.id):
            raise ValidationError("You cannot suspend your own account.")

        admin.status = AdminUser.Status.SUSPENDED
        admin.save(update_fields=["status", "updated_at"])
        cache.delete(f"auth_admin_{admin_id}")

        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.ADMIN_SUSPENDED,
            description=f"{admin.email} admin account was suspended."
            + (f" Reason: {reason}" if reason else ""),
            actor=acting_admin,
            subject=admin,
            metadata={"admin_id": str(admin.id), "reason": reason},
        )
        return admin

    def unsuspend_admin_user(self, acting_admin: AdminUser, admin_id: str) -> AdminUser:
        """Unsuspend a suspended admin user."""
        admin = self.get_admin_user(admin_id)
        if str(admin.id) == str(acting_admin.id):
            raise ValidationError("You cannot modify your own account status.")

        if admin.status != AdminUser.Status.SUSPENDED:
            raise ValidationError("This admin account is not suspended.")

        admin.status = AdminUser.Status.ACTIVE
        admin.save(update_fields=["status", "updated_at"])
        cache.delete(f"auth_admin_{admin_id}")

        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.ADMIN_UNSUSPENDED,
            description=f"{admin.email} admin account was unsuspended.",
            actor=acting_admin,
            subject=admin,
            metadata={"admin_id": str(admin.id)},
        )
        return admin

    def get_content_distribution(self) -> dict:
        return self.content_repo.get_content_distribution()

    def get_creator_leaderboard(self, limit: int = 10) -> list:
        return self.creator_repo.get_creator_leaderboard(limit=limit)

    def deactivate_user(self, user_id: str, admin: AdminUser) -> dict:
        user = self.user_repo.get_by_id(user_id)
        if not user.is_active:
            raise ValidationError("User is already deactivated.")

        if user.status == User.Status.SUSPENDED:
            raise ValidationError(
                "Cannot deactivate a suspended user. Lift the suspension first."
            )

        res = self.user_repo.deactivate_user(user)

        cache.delete(f"auth_user_{user_id}")
        self.moderation_repo.log_action(
            action_type=ModerationActionLog.ActionType.USER_DEACTIVATED,
            target_user=user,
            performed_by=admin,
        )

        log_activity = ActivityService().log_activity
        log_activity(
            action_type=ActivityLog.ActionType.USER_DEACTIVATED,
            description=f"{user.email} user account was deactivated.",
            actor=admin,
            subject=user,
            metadata={"user_id": str(user.id)},
        )

        return res

    def reactivate_user(self, user_id: str, admin: AdminUser) -> dict:
        user = self.user_repo.get_by_id(user_id)
        self.user_repo.reactivate_user(user)

        log_activity = ActivityService().log_activity
        log_activity(
            action_type=ActivityLog.ActionType.USER_REACTIVATED,
            description=f"{user.email} user account was Reactivated.",
            actor=admin,
            subject=user,
            metadata={"user_id": str(user.id)},
        )
        return {"detail": "User reactivated."}

    def get_profile_completion_status(self, admin: AdminUser) -> dict:
        missing = []

        if not admin.username:
            missing.append("username")

        if not admin.bio:
            missing.append("bio")

        is_complete = len(missing) == 0

        return {
            "is_complete": is_complete,
            "missing_fields": missing,
            "can_use_studio": admin.can_use_studio,
            "is_verified": admin.is_verified,
        }
