from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiParameter,
    OpenApiTypes,
)
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import AllowAny, IsAuthenticated

from skiflux.models import AdminUser, Permission
from skiflux.serializers.admin import (
    AdminChangePasswordSerializer,
    AdminForgotPasswordRequestSerializer,
    AdminLoginSerializer,
    AdminLogoutSerializer,
    AdminRefreshTokenSerializer,
    AdminResetPasswordConfirmSerializer,
    AdminVerifyForgotPasswordCodeSerializer,
    AssignAdminRolesSerializer,
    CreateAdminUserSerializer,
    CreateRoleSerializer,
    SuspendAdminSerializer,
    UpdateAdminUserSerializer,
    UpdateRoleSerializer,
    OverviewContentDistributionSerializer,
)

from skiflux.serializers.creator import CreatorProfileCompletionSerializer

from skiflux.serializers.user import (
    UserManagementListSerializer,
    UserManagementStatsSerializer,
)

from skiflux.serializers.creator import (
    CreatorLeaderBoardSerializer,
    AudienceDistributionSerializer,
    RevenueGrowthSerializer,
)
from skiflux.serializers.content import (
    SeasonPerformanceSerializer,
)

from skiflux.services.admin_service import AdminService
from skiflux.services.creator_management_service import CreatorManagementService
from skiflux.utils import (
    AdminJWTAuthentication,
    AdminLoginRateThrottle,
    APIResponse,
    ForgotPasswordRateThrottle,
)
from skiflux.utils.pagination import RecommendationPaginator

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


def _require_super_admin(admin: AdminUser):
    if not admin.is_super_admin:
        raise PermissionDenied("Only super admins can perform this action.")


def _require_permission(admin: AdminUser, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


@extend_schema(
    summary="Admin Login",
    description="Authenticate an admin user.Returns access and refresh tokens.",
    request=AdminLoginSerializer,
    responses={200: OpenApiResponse(description="Login successful.")},
    tags=["Admin › Auth"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AdminLoginRateThrottle])
def admin_login(request):
    admin_service = AdminService()
    serializer = AdminLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        data = admin_service.login(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Login successful.",
            data=data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Admin Forgot Password",
    description="Send a reset OTP to an admin email if the admin exists.",
    request=AdminForgotPasswordRequestSerializer,
    responses={
        200: OpenApiResponse(
            description="Sends a reset code to admin email if the email exists."
        )
    },
    tags=["Admin › Auth"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ForgotPasswordRateThrottle])
def admin_forgot_password(request):
    admin_service = AdminService()
    serializer = AdminForgotPasswordRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        admin_service.forgot_password(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="A reset code has been sent.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Verify Admin Password OTP",
    description="Verifies the 6-digit OTP sent during admin forgot password.",
    request=AdminVerifyForgotPasswordCodeSerializer,
    responses={
        200: OpenApiResponse(
            description="Password OTP verified successfully.",
        )
    },
    tags=["Admin › Auth"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def admin_verify_password_otp(request):
    admin_service = AdminService()
    serializer = AdminVerifyForgotPasswordCodeSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        admin_service.verify_password_otp(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Password OTP verified successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Admin Reset Password",
    description="Verify OTP and reset an admin password.",
    request=AdminResetPasswordConfirmSerializer,
    responses={
        200: OpenApiResponse(
            description="Password has been reset successfully.",
        )
    },
    tags=["Admin › Auth"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def admin_reset_password(request):
    admin_service = AdminService()
    serializer = AdminResetPasswordConfirmSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        validated_data = serializer.validated_data.copy()
        validated_data.pop("confirm_new_password", None)
        admin_service.reset_password(**validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Password has been reset successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Admin Token Refresh",
    description="Exchange a valid admin refresh token for a new access token.",
    request=AdminRefreshTokenSerializer,
    responses={200: OpenApiResponse(description="Returns new access_token.")},
    tags=["Admin › Auth"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def admin_token_refresh(request):
    admin_service = AdminService()
    serializer = AdminRefreshTokenSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        tokens = admin_service.token_refresh(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Token refreshed successfully.",
            data=tokens,
        )
    except ValueError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=str(e),
        )


@extend_schema(
    summary="Admin Logout",
    description="Blacklist the admin refresh token, ending the session.",
    request=AdminLogoutSerializer,
    responses={200: OpenApiResponse(description="Logged out successfully.")},
    tags=["Admin › Auth"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def admin_logout(request):
    admin_service = AdminService()
    serializer = AdminLogoutSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        admin_service.logout(**serializer.validated_data)
        access_token = request.auth
        if access_token:
            from skiflux.utils import blacklist_token

            blacklist_token(access_token)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Logged out successfully.",
        )
    except ValueError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


@extend_schema(
    summary="Admin Change Password",
    description=(
        "Change the current admin user's password."
        "Requires current password verification."
    ),
    request=AdminChangePasswordSerializer,
    responses={200: OpenApiResponse(description="Password changed successfully.")},
    tags=["Admin › Auth"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def admin_change_password(request):
    admin_service = AdminService()
    serializer = AdminChangePasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        admin_service.change_password(
            admin_id=request.user.id,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Password changed successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="List Available Permissions",
    description="Returns every known permission codename and its label. "
    "Use this to build the role-creation UI.",
    responses={200: OpenApiResponse(description="List of permission objects.")},
    tags=["Admin › Roles"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_permissions(request):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ROLES_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Available permissions.",
        data=admin_service.available_permissions(),
    )


@extend_schema(
    summary="List Roles",
    description="Returns all custom roles defined in the admin portal.",
    responses={200: OpenApiResponse(description="List of roles.")},
    tags=["Admin › Roles"],
    operation_id="admin_roles_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_roles(request):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ROLES_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    roles = admin_service.list_roles()
    data = [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "permissions": r.permissions,
            "is_custom": r.is_custom,
            "grants_studio_access": r.grants_studio_access,
            "created_at": r.created_at.isoformat(),
        }
        for r in roles
    ]
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Roles retrieved.",
        data=data,
    )


@extend_schema(
    summary="Create Role",
    description="Super admin creates a new custom rolewith a set of permissions.",
    request=CreateRoleSerializer,
    responses={201: OpenApiResponse(description="Role created.")},
    tags=["Admin › Roles"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def create_role(request):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ROLES_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    serializer = CreateRoleSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        role = admin_service.create_role(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_201_CREATED,
            message="Role created successfully.",
            data={
                "id": str(role.id),
                "name": role.name,
                "description": role.description,
                "permissions": role.permissions,
            },
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Get Role",
    description="Retrieve a single role by ID.",
    responses={200: OpenApiResponse(description="Role details.")},
    tags=["Admin › Roles"],
    operation_id="admin_roles_retrieve",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_role(request, role_id: str):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ROLES_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    try:
        role = admin_service.get_role(role_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Role retrieved.",
            data={
                "id": str(role.id),
                "name": role.name,
                "description": role.description,
                "permissions": role.permissions,
                "is_custom": role.is_custom,
                "created_at": role.created_at.isoformat(),
            },
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=e.detail,
        )


@extend_schema(
    summary="Update Role",
    description="Super admin updates a role's name, description, or permissions.",
    request=UpdateRoleSerializer,
    responses={200: OpenApiResponse(description="Role updated.")},
    tags=["Admin › Roles"],
)
@api_view(["PATCH"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def update_role(request, role_id: str):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ROLES_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    serializer = UpdateRoleSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        role = admin_service.update_role(role_id, **serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Role updated successfully.",
            data={
                "id": str(role.id),
                "name": role.name,
                "description": role.description,
                "permissions": role.permissions,
            },
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Delete Role",
    description="Super admin deletes a role. "
    "Fails if any admin user is currently assigned to it.",
    responses={200: OpenApiResponse(description="Role deleted.")},
    tags=["Admin › Roles"],
)
@api_view(["DELETE"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def delete_role(request, role_id: str):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ROLES_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    try:
        admin_service.delete_role(role_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Role deleted successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="List Admin Users",
    description=(
        "Returns a paginated list of admin portal users, "
        "with optional filtering by role name."
    ),
    parameters=[
        OpenApiParameter(
            name="role_name",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Filter admin users by role name.",
        ),
        OpenApiParameter(
            name="role_type",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Filter admin users by role type.",
        ),
    ],
    responses={200: OpenApiResponse(description="Paginated list of admin users.")},
    tags=["Admin › Users"],
    operation_id="admin_users_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_admin_users(request):

    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ADMIN_USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    # Get role_name filter from query params
    role_name = request.query_params.get("role_name")
    role_type = request.query_params.get("role_type")

    # Get queryset with optional role filtering
    admins_qs = admin_service.repo.list_all_queryset(
        role_name=role_name, role_type=role_type
    )

    # Apply pagination
    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(admins_qs, request)

    if page is not None:
        data = [
            {
                **AdminService.serialize_admin(a),
                "last_login": a.last_login.isoformat() if a.last_login else None,
                "created_at": a.created_at.isoformat(),
                "created_by": (str(a.created_by.id) if a.created_by else None),
            }
            for a in page
        ]
        response_data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": data,
        }
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Admin users retrieved.",
            data=response_data,
        )

    # Fallback if pagination is None
    data = [
        {
            **AdminService.serialize_admin(a),
            "last_login": a.last_login.isoformat() if a.last_login else None,
            "created_at": a.created_at.isoformat(),
            "created_by": (str(a.created_by.id) if a.created_by else None),
        }
        for a in admins_qs
    ]
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Admin users retrieved.",
        data={
            "count": admins_qs.count(),
            "next": None,
            "previous": None,
            "results": data,
        },
    )


@extend_schema(
    summary="Create Admin User",
    description="Super admin creates a new adminportal user and assigns a role.",
    request=CreateAdminUserSerializer,
    responses={201: OpenApiResponse(description="Admin user created.")},
    tags=["Admin › Users"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def create_admin_user(request):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ADMIN_USERS_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    serializer = CreateAdminUserSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        admin = admin_service.create_admin_user(
            acting_admin=request.user,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_201_CREATED,
            message="Admin user created successfully.",
            data=AdminService.serialize_admin(
                admin_service.get_admin_user(str(admin.id))
            ),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Get Admin User",
    description="Retrieve an admin user by ID.",
    responses={200: OpenApiResponse(description="Admin user details.")},
    tags=["Admin › Users"],
    operation_id="admin_users_retrieve",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_admin_user(request, admin_id: str):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ADMIN_USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    try:
        admin = admin_service.get_admin_user(admin_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Admin user retrieved.",
            data=AdminService.serialize_admin(admin),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=e.detail,
        )


@extend_schema(
    summary="Update Admin User",
    description="Super admin updates an admin user's details or role assignment.",
    request=UpdateAdminUserSerializer,
    responses={200: OpenApiResponse(description="Admin user updated.")},
    tags=["Admin › Users"],
)
@api_view(["PATCH"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def update_admin_user(request, admin_id: str):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ADMIN_USERS_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    serializer = UpdateAdminUserSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        admin = admin_service.update_admin_user(
            request.user, admin_id, **serializer.validated_data
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Admin user updated successfully.",
            data=AdminService.serialize_admin(admin),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Assign or Remove Admin Roles",
    description=(
        "Add or remove custom portal roles (role IDs) and/or built-in role types "
        "(add_role_types / remove_role_types). Grant studio access to a platform "
        "admin by adding the built-in 'creator' role type while keeping role_type "
        "as 'admin'. Requires roles.manage for role type changes."
    ),
    request=AssignAdminRolesSerializer,
    responses={200: OpenApiResponse(description="Roles updated.")},
    tags=["Admin › Users"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def assign_admin_roles(request, admin_id: str):
    admin_service = AdminService()
    serializer = AssignAdminRolesSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    validated = serializer.validated_data
    try:
        if validated.get("add_role_types") or validated.get("remove_role_types"):
            _require_permission(request.user, Permission.ROLES_MANAGE)
        if validated.get("add_role_ids") or validated.get("remove_role_ids"):
            _require_permission(request.user, Permission.ADMIN_USERS_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    try:
        admin = admin_service.assign_roles(
            acting_admin=request.user,
            admin_id=admin_id,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Roles updated successfully.",
            data=AdminService.serialize_admin(admin),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Deactivate Admin User",
    description="Super admin deactivates an admin portal user (soft delete).",
    responses={200: OpenApiResponse(description="Admin user deactivated.")},
    tags=["Admin › Users"],
)
@api_view(["DELETE"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def deactivate_admin_user(request, admin_id: str):
    admin_service = AdminService()
    try:
        _require_super_admin(request.user)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    try:
        admin_service.deactivate_admin_user(request.user, admin_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Admin user deactivated successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Suspend Admin User",
    description=(
        "Super admin suspends an admin user (temporary restriction with reason)."
    ),
    request=SuspendAdminSerializer,
    responses={200: OpenApiResponse(description="Admin user suspended.")},
    tags=["Admin › Users"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def suspend_admin_user(request, admin_id: str):
    admin_service = AdminService()
    try:
        _require_super_admin(request.user)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    serializer = SuspendAdminSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    try:
        reason = serializer.validated_data.get("reason", "")
        admin_service.suspend_admin_user(request.user, admin_id, reason=reason)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Admin user suspended successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Unsuspend Admin User",
    description="Super admin unsuspends a suspended admin user.",
    responses={200: OpenApiResponse(description="Admin user unsuspended.")},
    tags=["Admin › Users"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def unsuspend_admin_user(request, admin_id: str):
    admin_service = AdminService()
    try:
        _require_super_admin(request.user)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    try:
        admin_service.unsuspend_admin_user(request.user, admin_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Admin user unsuspended successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="List Roles with Member Count",
    description=(
        "Returns all roles with the total count of admin users assigned to each role. "
        "Only accessible by super admins."
    ),
    responses={200: OpenApiResponse(description="List of roles with member counts.")},
    tags=["Admin › Roles"],
    operation_id="admin_roles_with_member_count",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_roles_with_member_count(request):
    admin_service = AdminService()
    try:
        _require_super_admin(request.user)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    try:
        roles = admin_service.list_roles()
        data = []
        for role in roles:
            member_count = role.admin_users.count()
            data.append(
                {
                    "id": str(role.id),
                    "name": role.name,
                    "description": role.description,
                    "permissions": role.permissions,
                    "is_custom": role.is_custom,
                    "grants_studio_access": role.grants_studio_access,
                    "total_members": member_count,
                    "created_at": role.created_at.isoformat(),
                    "updated_at": role.updated_at.isoformat(),
                }
            )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Roles with member count retrieved.",
            data=data,
        )
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )


@extend_schema(
    summary="Get Learner Users Statistics",
    description=(
        "Returns dashboard statistics for learner users including total count, "
        "active, suspended, deactivated, and new users this week. Admin-only endpoint."
    ),
    responses={
        200: OpenApiResponse(
            description="User statistics retrieved successfully.",
            response=UserManagementStatsSerializer,
        )
    },
    tags=["Admin > Learner"],
    operation_id="admin_learners_stats",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_learner_users_stats(request):
    """
    Calculate and return user management dashboard statistics.
    """
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.ADMIN_USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    stats_data = admin_service.get_learner_stats()

    serializer = UserManagementStatsSerializer(stats_data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="User statistics retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="List Learner Users",
    description=(
        "Returns a paginated list of all learner users with their stats including "
        "tasks completed, status, skillworld, etc. Admin-only endpoint."
    ),
    parameters=[
        OpenApiParameter(
            name="status",
            type=str,
            description="Filter by user status (active, suspended, deactivated)",
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name="skillworld",
            type=str,
            description="Filter by skillworld (design, code, writing, marketing)",
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name="search",
            type=str,
            description="Search by email or name",
            location=OpenApiParameter.QUERY,
        ),
        OpenApiParameter(
            name="page",
            type=int,
            description="Page number for pagination",
            location=OpenApiParameter.QUERY,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Paginated list of learner users with tasks_done count."
        )
    },
    tags=["Admin > Learner"],
    operation_id="admin_learners_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_learner_users(request):
    admin_service = AdminService()

    try:
        _require_permission(request.user, Permission.ADMIN_USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    status_filter = request.query_params.get("status")
    skillworld_filter = request.query_params.get("skillworld")
    search_query = request.query_params.get("search", "").strip()

    qs = admin_service.list_learners(
        status=status_filter,
        skillworld=skillworld_filter,
        search=search_query,
    )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)

    serializer = UserManagementListSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Learner users retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Get Content Distribution Overview",
    description=(
        "Returns an overview of content distribution across the platform, including "
        "total episode count, project-based task count, "
        "and assessment-based task count. "
        "Admin-only endpoint."
    ),
    responses={
        200: OpenApiResponse(
            description="Content distribution overview retrieved successfully.",
            response=OverviewContentDistributionSerializer,
        )
    },
    tags=["Admin › Content"],
    operation_id="admin_content_distribution_overview",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_content_distribution_overview(request):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.CONTENT_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    overview_data = admin_service.get_content_distribution()

    serializer = OverviewContentDistributionSerializer(overview_data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Content distribution overview retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Creator Leaderboard",
    description=(
        "Return a leaderboard of top creators based on the number of episodes created, "
        "with trend data compared to the previous month. Admin-only endpoint."
    ),
    parameters=[
        OpenApiParameter(
            name="limit",
            type=int,
            location=OpenApiParameter.QUERY,
            description="Number of creators to return (default: 10, max: 100).",
            required=False,
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Creator leaderboard retrieved successfully.",
            response=CreatorLeaderBoardSerializer(many=True),
        )
    },
    tags=["Admin › Creator Management"],
    operation_id="admin_creator_leaderboard",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_creator_leaderboard(request):
    admin_service = AdminService()
    try:
        _require_permission(request.user, Permission.CREATOR_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    try:
        limit = int(request.query_params.get("limit", 10))
        limit = max(1, min(limit, 100))
    except (TypeError, ValueError):
        limit = 10

    leaderboard_data = admin_service.get_creator_leaderboard(limit=limit)

    serializer = CreatorLeaderBoardSerializer(leaderboard_data, many=True)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Creator leaderboard retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Creator Audience",
    description=(
        "Return the audience distribution for a specific creator, "
        "showing the percentage of the audience from different countries. "
        "Admin-only endpoint."
    ),
    parameters=[
        OpenApiParameter(
            name="limit",
            type=int,
            location=OpenApiParameter.QUERY,
            description="Number of audience entries to return (default: 10, max: 100).",
            required=False,
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Creator audience distribution retrieved successfully.",
            response=AudienceDistributionSerializer(many=True),
        )
    },
    tags=["Admin › Creator Management"],
    operation_id="admin_creator_audience_distribution",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_creator_audience_distribution(request, creator_id):
    creator_service = CreatorManagementService()
    limit = request.query_params.get("limit")
    if not creator_id:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="creator_id query parameter is required.",
        )

    # Make either the owner or only admin with permission have access
    if str(request.user.id) != str(creator_id):
        try:
            _require_permission(request.user, Permission.CREATOR_VIEW)
        except PermissionDenied as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_403_FORBIDDEN,
                message=str(e),
            )

    try:
        audience_data = creator_service.get_creator_audience_distribution(
            creator_id, limit=int(limit) if limit else None
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=e.detail,
        )

    serializer = AudienceDistributionSerializer(audience_data, many=True)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Creator audience distribution retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Creator Revenue Growth",
    description=(
        "Return the revenue growth for a specific creator, "
        "showing current and previous period comparisons. Admin-only endpoint."
        "Labels only include periods where at least one purchase occurred "
        "in either the current or previous period. Missing periods had zero revenue."
    ),
    parameters=[
        OpenApiParameter(
            name="period",
            type=str,
            location=OpenApiParameter.QUERY,
            description=(
                "Time period for revenue data. "
                "One of: week, month, year (default: week)."
            ),
            required=False,
            enum=["week", "month", "year"],
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Creator revenue growth retrieved successfully.",
            response=RevenueGrowthSerializer,
        )
    },
    tags=["Admin › Creator Management"],
    operation_id="admin_creator_revenue_growth",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_creator_revenue_growth(request, creator_id):
    creator_service = CreatorManagementService()
    period = request.query_params.get("period", "week")

    if not creator_id:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="creator_id query parameter is required.",
        )

    if period not in ("week", "month", "year"):
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid period. Must be one of: week, month, year.",
        )

    # Make either the owner or only admin with permission have access
    if str(request.user.id) != str(creator_id):
        try:
            _require_permission(request.user, Permission.CREATOR_VIEW)
        except PermissionDenied as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_403_FORBIDDEN,
                message=str(e),
            )

    try:
        revenue_data = creator_service.get_creator_revenue_growth(
            creator_id,
            period=period,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=e.detail,
        )

    serializer = RevenueGrowthSerializer(revenue_data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Creator revenue growth retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Creator Season Performance",
    description=(
        "Returns paginated season-level performance metrics for a creator "
        "including sales, completion rate, revenue and rating. Admin-only endpoint."
    ),
    responses={
        200: OpenApiResponse(
            description="Creator season performance retrieved successfully.",
            response=SeasonPerformanceSerializer(many=True),
        )
    },
    tags=["Admin › Creator Management"],
    operation_id="admin_creator_season_performance",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_creator_seasons_performance(request, creator_id):
    creator_service = CreatorManagementService()

    if str(request.user.id) != str(creator_id):
        try:
            _require_permission(request.user, Permission.CREATOR_VIEW)
        except PermissionDenied as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_403_FORBIDDEN,
                message=str(e),
            )

    try:
        qs = creator_service.get_creator_seasons_performance(creator_id)
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=e.detail,
        )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)
    serializer = SeasonPerformanceSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Creator seasons performance retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Get Creator Profile Completion Status",
    description=(
        "Returns whether the creator's profile is complete. "
        "Frontend should call this before any studio action "
        "and redirect to profile setup if is_complete is false."
    ),
    responses={
        200: OpenApiResponse(
            description="Profile completion status.",
            response=CreatorProfileCompletionSerializer,
        ),
    },
    tags=["Admin › Creator Profile"],
    operation_id="studio_profile_completion",
)
@api_view(["GET"])
@authentication_classes([AdminJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_profile_completion_status(request):
    admin = request.user

    if not isinstance(admin, AdminUser):
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message="Creator account required.",
        )

    service = AdminService()
    data = service.get_profile_completion_status(admin)
    serializer = CreatorProfileCompletionSerializer(data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Profile completion status retrieved.",
        data=serializer.data,
    )
