from django.contrib.auth.password_validation import validate_password
from django.core import exceptions as django_exceptions
from rest_framework import serializers
from skiflux.models import AdminUser, Permission


class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class AdminRefreshTokenSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class AdminLogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class AdminForgotPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class AdminVerifyForgotPasswordCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(write_only=True, min_length=6, max_length=6)

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class AdminResetPasswordConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(write_only=True, min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_new_password = serializers.CharField(write_only=True)

    def validate_email(self, value: str) -> str:
        return value.lower().strip()

    def validate(self, attrs: dict) -> dict:
        if attrs.get("new_password") != attrs.get("confirm_new_password"):
            raise serializers.ValidationError(
                {"confirm_new_password": "Passwords do not match."}
            )
        return attrs


class AdminChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, min_length=1)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value: str) -> str:
        # Validate the new password using Django's password validators
        try:
            validate_password(value)
        except django_exceptions.ValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs.get("new_password") != attrs.get("confirm_new_password"):
            raise serializers.ValidationError(
                {"confirm_new_password": "Passwords do not match."}
            )
        return attrs


class CreateRoleSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=[(p, p) for p in Permission.ALL]),
        allow_empty=True,
        default=list,
        help_text="List of permission codenames to grant. Must be from the known set.",
    )

    def validate_name(self, value: str) -> str:
        return value.strip()


class UpdateRoleSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=[(p, p) for p in Permission.ALL]),
        required=False,
        help_text="Full replacement list of permission codenames.",
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError(
                "At least one field (name, description, permissions) must be provided."
            )
        return attrs


class CreateAdminUserSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=255)
    last_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    email = serializers.EmailField()
    role_type = serializers.ChoiceField(
        choices=[AdminUser.RoleType.ADMIN, AdminUser.RoleType.CREATOR]
    )
    role_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
    )

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class AssignAdminRolesSerializer(serializers.Serializer):
    add_role_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        help_text="Custom portal role IDs to add.",
    )
    remove_role_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
        help_text="Custom portal role IDs to remove.",
    )
    add_role_types = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[AdminUser.RoleType.ADMIN, AdminUser.RoleType.CREATOR]
        ),
        required=False,
        allow_empty=True,
        default=list,
        help_text=(
            "Built-in role types to add (e.g. 'creator' on a platform admin "
            "without changing their primary role_type)."
        ),
    )
    remove_role_types = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[AdminUser.RoleType.ADMIN, AdminUser.RoleType.CREATOR]
        ),
        required=False,
        allow_empty=True,
        default=list,
        help_text="Built-in role types to remove from the account.",
    )

    def validate(self, attrs: dict) -> dict:
        if not any(
            [
                attrs.get("add_role_ids"),
                attrs.get("remove_role_ids"),
                attrs.get("add_role_types"),
                attrs.get("remove_role_types"),
            ]
        ):
            raise serializers.ValidationError(
                "Provide at least one of add_role_ids, remove_role_ids, "
                "add_role_types, or remove_role_types."
            )
        return attrs


class UpdateAdminUserSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=255, required=False)
    last_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
    )
    role_type = serializers.ChoiceField(
        choices=[AdminUser.RoleType.ADMIN, AdminUser.RoleType.CREATOR],
        required=False,
    )
    is_active = serializers.BooleanField(required=False)
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        required=False,
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError(
                "At least one field must be provided to update."
            )
        return attrs


class VerificationStatsSerializer(serializers.Serializer):
    pending_count = serializers.IntegerField()
    pending_change_pct = serializers.FloatField()
    avg_wait_secs = serializers.FloatField()
    avg_response_time_minutes = serializers.FloatField()
    sla_breach_count = serializers.IntegerField()


class VerificationEpisodeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    season_title = serializers.CharField()
    season_skillworld = serializers.CharField(allow_null=True)
    creator_name = serializers.CharField()
    creator_avatar_url = serializers.CharField(allow_null=True)
    submitted_at = serializers.DateTimeField()
    sla_deadline = serializers.DateTimeField()
    sla_breached = serializers.BooleanField()
    priority = serializers.ChoiceField(choices=["low", "medium", "high"])
    status = serializers.CharField()


class VerificationFilterSerializer(serializers.Serializer):
    priority = serializers.ChoiceField(
        choices=["low", "medium", "high"],
        required=False,
    )
    ordering = serializers.ChoiceField(
        choices=["oldest", "newest"],
        required=False,
        default="oldest",
    )
    page = serializers.CharField(
        required=False,
    )
    creator_id = serializers.UUIDField(required=False)


class BulkEpisodeReviewSerializer(serializers.Serializer):
    episode_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
    )
    action = serializers.ChoiceField(choices=["approve", "reject"])
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate(self, attrs):
        if attrs["action"] == "reject" and not attrs.get("reason"):
            raise serializers.ValidationError(
                {"reason": "Reason is required when bulk rejecting."}
            )
        return attrs


class OverviewContentDistributionSerializer(serializers.Serializer):
    episode_count = serializers.IntegerField()
    project_based_task_count = serializers.IntegerField()
    assessment_based_task_count = serializers.IntegerField()


class DashboardOverviewSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    total_users_growth_percentage = serializers.DecimalField(
        max_digits=5,
        decimal_places=1,
    )

    active_creators = serializers.IntegerField()
    active_creators_growth_percentage = serializers.DecimalField(
        max_digits=5,
        decimal_places=1,
    )

    revenue_last_24h = serializers.DecimalField(max_digits=12, decimal_places=2)

    pending_verifications = serializers.IntegerField()
    is_pending_verifications_high_priority = serializers.BooleanField()


class UserGrowthDataPointSerializer(serializers.Serializer):
    month = serializers.DateTimeField(format="%b %Y")
    count = serializers.IntegerField()


class UserGrowthSerializer(serializers.Serializer):
    data = UserGrowthDataPointSerializer(many=True)
    percentage_change = serializers.FloatField()
    is_increase = serializers.BooleanField()


class SuspendAdminSerializer(serializers.Serializer):
    """Serializer for suspending an admin user."""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Reason for suspension (optional)",
    )


class UnsuspendAdminSerializer(serializers.Serializer):
    """Serializer for unsuspending a suspended admin user."""

    pass
