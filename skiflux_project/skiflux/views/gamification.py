from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from skiflux.repositories.gamification_repository import GamificationRepository
from skiflux.serializers.gamification import (
    BadgeCreateSerializer,
    BadgeSerializer,
    PlatformTaskAdminSerializer,
    PlatformTaskCreateSerializer,
    PlatformTaskListFilterSerializer,
    PlatformTaskUserSerializer,
    StreakSummarySerializer,
    UserBadgeSerializer,
)
from skiflux.services.gamification_service import GamificationService
from skiflux.services.platform_task_service import PlatformTaskService
from skiflux.tasks.content import upload_media_from_minio_task
from skiflux.utils import AdminJWTAuthentication, APIResponse, JWTAuthentication
from skiflux.utils.media import upload_to_minio
from skiflux.utils.permissions import IsSuperAdmin

_learner_auth = [JWTAuthentication]
_admin_auth = [AdminJWTAuthentication]


def _task_service():
    return PlatformTaskService()


def _badge_repo():
    return GamificationRepository()


def _schedule_badge_icon_upload(badge, icon_file):
    minio_key = upload_to_minio(icon_file, folder="skiflux_badges")
    transaction.on_commit(
        lambda badge_id=str(badge.id), key=minio_key: (
            upload_media_from_minio_task.delay(
                badge_id,
                key,
                "icon_public_id",
                "Badge",
                "image",
            )
        )
    )


@extend_schema(
    summary="Get user badges",
    description="Retrieve the badges earned by the authenticated user.",
    responses={200: UserBadgeSerializer(many=True)},
    tags=["Learner > Gamification"],
)
@api_view(["GET"])
@authentication_classes(_learner_auth)
@permission_classes([IsAuthenticated])
def get_user_badges(request):
    service = GamificationService()
    badges = service.get_user_badges(request.user)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="User badges retrieved successfully.",
        data=UserBadgeSerializer(badges, many=True).data,
    )


@extend_schema(
    summary="Get streak summary",
    description=(
        "Returns streak stats for the authenticated user: current streak, "
        "weekly day statuses, best streak, total streak XP earned, and "
        "milestone progress."
    ),
    responses={200: StreakSummarySerializer},
    tags=["Learner > Gamification"],
)
@api_view(["GET"])
@authentication_classes(_learner_auth)
@permission_classes([IsAuthenticated])
def get_user_streak(request):
    service = GamificationService()
    data = service.get_streak_summary(request.user)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Streak summary retrieved successfully.",
        data=StreakSummarySerializer(data).data,
    )


@extend_schema(
    summary="Get platform tasks",
    description=(
        "Retrieve active platform tasks with the user's progress and claim status."
    ),
    responses={200: PlatformTaskUserSerializer(many=True)},
    tags=["Learner > Gamification"],
)
@api_view(["GET"])
@authentication_classes(_learner_auth)
@permission_classes([IsAuthenticated])
def list_platform_tasks(request):
    service = _task_service()
    tasks = service.get_tasks_with_status(request.user)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Platform tasks retrieved successfully.",
        data=tasks,
    )


@extend_schema(
    summary="Start a platform task",
    description=(
        "Mark a platform task as started. Useful for timed or external-link tasks."
    ),
    responses={200: PlatformTaskUserSerializer},
    tags=["Learner > Gamification"],
)
@api_view(["POST"])
@authentication_classes(_learner_auth)
@permission_classes([IsAuthenticated])
def start_platform_task(request, task_id: str):
    service = _task_service()
    try:
        data = service.start_task(request.user, task_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform task started.",
            data=data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Submit a manual platform task",
    description="Marks a manual platform task as ready to claim.",
    responses={200: PlatformTaskUserSerializer},
    tags=["Learner > Gamification"],
)
@api_view(["POST"])
@authentication_classes(_learner_auth)
@permission_classes([IsAuthenticated])
def submit_platform_task(request, task_id: str):
    service = _task_service()
    try:
        data = service.submit_task(request.user, task_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform task submitted. You can now claim your reward.",
            data=data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Claim a platform task reward",
    description="Claim XP and Skillcoin rewards for a claimable platform task.",
    responses={200: PlatformTaskUserSerializer},
    tags=["Learner > Gamification"],
)
@api_view(["POST"])
@authentication_classes(_learner_auth)
@permission_classes([IsAuthenticated])
def claim_platform_task(request, task_id: str):
    service = _task_service()
    try:
        data = service.claim_task(request.user, task_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform task reward claimed successfully.",
            data=data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Complete a platform task",
    description=(
        "Backward-compatible endpoint. "
        "Manual tasks are submitted and claimed in one step. "
        "Automatic tasks must already be claimable."
    ),
    responses={200: PlatformTaskUserSerializer},
    tags=["Learner > Gamification"],
)
@api_view(["POST"])
@authentication_classes(_learner_auth)
@permission_classes([IsAuthenticated])
def complete_platform_task(request, task_id: str):
    service = _task_service()
    try:
        data = service.complete_task(request.user, task_id)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform task completed successfully.",
            data=data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    methods=["GET"],
    summary="List platform tasks",
    description="Superadmin endpoint to list and filter platform tasks.",
    parameters=[
        OpenApiParameter(name="is_active", type=bool),
        OpenApiParameter(name="category", type=str),
        OpenApiParameter(name="search", type=str),
    ],
    responses={200: PlatformTaskAdminSerializer(many=True)},
    tags=["Superadmin > Gamification"],
)
@extend_schema(
    methods=["POST"],
    summary="Create a platform task",
    description="Superadmin endpoint to create a new platform task.",
    request=PlatformTaskCreateSerializer,
    responses={201: PlatformTaskAdminSerializer},
    tags=["Superadmin > Gamification"],
)
@api_view(["GET", "POST"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def admin_platform_tasks(request):
    if request.method == "GET":
        filters = PlatformTaskListFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        service = _task_service()
        tasks = service.list_admin_tasks(**filters.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform tasks retrieved successfully.",
            data=PlatformTaskAdminSerializer(tasks, many=True).data,
        )

    service = _task_service()
    serializer = PlatformTaskCreateSerializer(
        data=request.data,
        context={"service": service},
    )
    if serializer.is_valid():
        task = serializer.save()
        return APIResponse(
            status="success",
            status_code=status.HTTP_201_CREATED,
            message="Platform task created successfully.",
            data=PlatformTaskAdminSerializer(task).data,
        )
    return APIResponse(
        status="error",
        status_code=status.HTTP_400_BAD_REQUEST,
        message=serializer.errors,
    )


@extend_schema(
    methods=["GET"],
    summary="Get platform task",
    description="Superadmin endpoint to retrieve a single platform task.",
    responses={200: PlatformTaskAdminSerializer},
    tags=["Superadmin > Gamification"],
)
@extend_schema(
    methods=["PATCH"],
    summary="Update a platform task",
    description="Superadmin endpoint to update an existing platform task.",
    request=PlatformTaskCreateSerializer,
    responses={200: PlatformTaskAdminSerializer},
    tags=["Superadmin > Gamification"],
)
@extend_schema(
    methods=["DELETE"],
    summary="Deactivate a platform task",
    description="Superadmin endpoint to deactivate a platform task.",
    responses={200: PlatformTaskAdminSerializer},
    tags=["Superadmin > Gamification"],
)
@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def admin_platform_task_detail(request, task_id: str):
    service = _task_service()
    try:
        task = service.get_admin_task(task_id)
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=e.detail,
        )

    if request.method == "GET":
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform task retrieved successfully.",
            data=PlatformTaskAdminSerializer(task).data,
        )

    if request.method == "PATCH":
        serializer = PlatformTaskCreateSerializer(
            task,
            data=request.data,
            partial=True,
            context={"service": service},
        )
        if serializer.is_valid():
            task = serializer.save()
            return APIResponse(
                status="success",
                status_code=status.HTTP_200_OK,
                message="Platform task updated successfully.",
                data=PlatformTaskAdminSerializer(task).data,
            )
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    task = service.deactivate_task(task_id)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Platform task deactivated successfully.",
        data=PlatformTaskAdminSerializer(task).data,
    )


@extend_schema(
    summary="List platform tasks",
    description="Superadmin endpoint to list and filter platform tasks.",
    deprecated=True,
    tags=["Superadmin > Gamification"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def list_admin_platform_tasks(request):
    return admin_platform_tasks(request)


@extend_schema(
    summary="Get platform task",
    deprecated=True,
    tags=["Superadmin > Gamification"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def get_admin_platform_task(request, task_id: str):
    return admin_platform_task_detail(request, task_id)


@extend_schema(
    summary="Create a platform task",
    deprecated=True,
    tags=["Superadmin > Gamification"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def create_platform_task(request):
    return admin_platform_tasks(request)


@extend_schema(
    summary="Update a platform task",
    deprecated=True,
    tags=["Superadmin > Gamification"],
)
@api_view(["PATCH"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def update_admin_platform_task(request, task_id: str):
    return admin_platform_task_detail(request, task_id)


@extend_schema(
    summary="Deactivate a platform task",
    deprecated=True,
    tags=["Superadmin > Gamification"],
)
@api_view(["DELETE"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def deactivate_admin_platform_task(request, task_id: str):
    return admin_platform_task_detail(request, task_id)


@extend_schema(
    summary="Create a badge",
    description=(
        "Superadmin endpoint to create a new badge. "
        "Send multipart/form-data to include an optional icon image."
    ),
    request={
        "multipart/form-data": BadgeCreateSerializer,
        "application/json": BadgeCreateSerializer,
    },
    responses={201: BadgeSerializer},
    tags=["Superadmin > Gamification"],
)
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def create_badge(request):
    icon_file = request.FILES.get("icon")
    data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
    data.pop("icon", None)

    serializer = BadgeCreateSerializer(data=data)
    if serializer.is_valid():
        badge = serializer.save()
        if icon_file:
            _schedule_badge_icon_upload(badge, icon_file)
        return APIResponse(
            status="success",
            status_code=status.HTTP_201_CREATED,
            message="Badge created successfully.",
            data=BadgeSerializer(badge).data,
        )
    return APIResponse(
        status="error",
        status_code=status.HTTP_400_BAD_REQUEST,
        message=serializer.errors,
    )


@extend_schema(
    methods=["GET"],
    summary="Get a badge",
    description="Superadmin endpoint to retrieve a badge by ID.",
    responses={200: BadgeSerializer},
    tags=["Superadmin > Gamification"],
)
@extend_schema(
    methods=["PATCH"],
    summary="Update a badge",
    description=(
        "Superadmin endpoint to update badge metadata and optionally upload icon."
    ),
    request={
        "multipart/form-data": BadgeCreateSerializer,
        "application/json": BadgeCreateSerializer,
    },
    responses={200: BadgeSerializer},
    tags=["Superadmin > Gamification"],
)
@api_view(["GET", "PATCH"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def admin_badge_detail(request, badge_id: str):
    repo = _badge_repo()
    badge = repo.get_badge_by_id(badge_id)
    if not badge:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message="Badge not found.",
        )

    if request.method == "GET":
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Badge retrieved successfully.",
            data=BadgeSerializer(badge).data,
        )

    icon_file = request.FILES.get("icon")
    data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
    data.pop("icon", None)

    serializer = BadgeCreateSerializer(badge, data=data, partial=True)
    if serializer.is_valid():
        badge = serializer.save()
        if icon_file:
            _schedule_badge_icon_upload(badge, icon_file)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Badge updated successfully.",
            data=BadgeSerializer(badge).data,
        )
    return APIResponse(
        status="error",
        status_code=status.HTTP_400_BAD_REQUEST,
        message=serializer.errors,
    )
