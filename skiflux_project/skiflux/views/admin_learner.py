from drf_spectacular.utils import (
    OpenApiResponse,
    OpenApiParameter,
    extend_schema,
)
from skiflux.serializers import (
    LearnerSuspendSerializer,
    DeactivateUserSerializer,
)

from skiflux.serializers.user import UserProfileSerializer
from skiflux.serializers.wallet import SkillcoinTransactionSerializer
from skiflux.serializers.support_serializers import SupportTicketListSerializer

from skiflux.models import User
from skiflux.repositories import UserRepository
from skiflux.services.support_service import SupportService
from skiflux.services.admin_service import AdminService
from skiflux.services.profile_service import UserProfileService
from skiflux.services.wallet_service import WalletService
from skiflux.services.moderation_service import ModerationService
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)

from skiflux.models import AdminUser, Permission
from skiflux.utils import (
    APIResponse,
    AdminJWTAuthentication,
)
from skiflux.utils.pagination import RecommendationPaginator

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


def _require_permission(admin: AdminUser, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


@extend_schema(
    summary="Suspend User",
    description=(
        "Directly suspend a user account without needing a comment context. "
        "Supports custom duration or permanent suspension."
    ),
    request=LearnerSuspendSerializer,
    responses={
        200: OpenApiResponse(description="User suspended."),
        400: OpenApiResponse(description="User not found or already suspended."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=["Admin > Learner"],
    operation_id="admin_moderation_suspend_user",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def suspend_user(request, user_id):
    try:
        _require_permission(request.user, Permission.MODERATION_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    if not user_id:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="User ID is required.",
        )

    serializer = LearnerSuspendSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    service = ModerationService()
    try:
        result = service.suspend_user_directly(
            user_id=str(user_id),
            admin=request.user,
            reason=serializer.validated_data["reason"],
            duration_days=serializer.validated_data.get("duration_days"),
        )
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message=result["detail"],
        data={"suspension_id": result["suspension_id"]},
    )


@extend_schema(
    summary="Get Learner Profile",
    description=(
        "Returns a learner's profile with stats as shown on the admin dashboard."
    ),
    responses={
        200: OpenApiResponse(
            description="Learner profile retrieved.",
            response=UserProfileSerializer,
        ),
        400: OpenApiResponse(description="User not found."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=["Admin > Learner"],
    operation_id="admin_learner_profile",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_learner_profile(request, user_id):
    try:
        _require_permission(request.user, Permission.ADMIN_USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = UserProfileService()

    try:
        user = UserRepository().get_by_id(user_id)
        if not user:
            raise Exception("User not found.")
        profile = service.get_profile(user)
        serializer = UserProfileSerializer(profile)
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Learner profile retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Deactivate User",
    description="Permanently deactivate a learner account.",
    request=DeactivateUserSerializer,
    responses={
        200: OpenApiResponse(description="User deactivated."),
        400: OpenApiResponse(description="User not found or already deactivated."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=["Admin > Learner"],
    operation_id="admin_learner_deactivate",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def deactivate_user(request, user_id):
    try:
        _require_permission(request.user, Permission.MODERATION_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    if not user_id:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="User ID is required.",
        )

    serializer = DeactivateUserSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    service = AdminService()

    try:
        result = service.deactivate_user(
            user_id=str(user_id),
            admin=request.user,
        )
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message=result["detail"],
    )


@extend_schema(
    summary="Reactivate User",
    description="Reactivate a learner account.",
    responses={
        200: OpenApiResponse(description="User Reactivated."),
        400: OpenApiResponse(description="User not found"),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=["Admin > Learner"],
    operation_id="admin_learner_reactivate",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def reactivate_user(request, user_id):
    try:
        _require_permission(request.user, Permission.MODERATION_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    if not user_id:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="User ID is required.",
        )
    service = AdminService()

    try:
        service.reactivate_user(
            user_id=str(user_id),
            admin=request.user,
        )
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="User Reactivated Successfully",
    )


@extend_schema(
    summary="Get Skillworlds",
    description="Returns all available skillworld options.",
    responses={
        200: OpenApiResponse(description="Skillworlds retrieved."),
    },
    tags=["Admin > Learner"],
    operation_id="admin_skillworlds",
)
@api_view(["GET"])
@permission_classes([AllowAny])
def get_skillworlds(request):
    skillworlds = [
        {"value": value, "label": label} for value, label in User.Skillworld.choices
    ]
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Skillworlds retrieved.",
        data=skillworlds,
    )


@extend_schema(
    summary="Get User Transactions",
    description=(
        "Retrieves all wallet transactions for a specific user (ledger history)."
    ),
    parameters=[
        OpenApiParameter(
            name="page",
            type=int,
            description="Page number for pagination",
            location=OpenApiParameter.QUERY,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="User transactions retrieved successfully.",
            response=SkillcoinTransactionSerializer(many=True),
        ),
        400: OpenApiResponse(description="Bad request."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=["Admin > Learner"],
    operation_id="admin_user_transactions",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_user_transactions(request, user_id):
    try:
        _require_permission(request.user, Permission.USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    if not user_id:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="User ID is required.",
        )

    service = WalletService()

    transactions = service.get_user_transactions(user_id)
    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(transactions, request)

    serializer = SkillcoinTransactionSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="User transactions retrieved successfully.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Get User Support Tickets",
    description="Retrieves all support tickets created by a specific user.",
    parameters=[
        OpenApiParameter(
            name="page",
            type=int,
            description="Page number for pagination",
            location=OpenApiParameter.QUERY,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="User tickets retrieved successfully.",
            response=SupportTicketListSerializer(many=True),
        ),
        400: OpenApiResponse(description="Bad request."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=["Admin > Learner"],
    operation_id="admin_user_support_tickets",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_user_support_tickets(request, user_id):
    try:
        _require_permission(request.user, Permission.USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    if not user_id:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="User ID is required.",
        )

    service = SupportService()

    tickets = service.get_ticket_by_user(user_id)
    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(tickets, request)

    serializer = SupportTicketListSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="User tickets retrieved successfully.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )
