from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from skiflux.models.activity import ActivityLog
from skiflux.models.role import Permission
from skiflux.serializers.activity import ActivityLogSerializer, ActivityStatsSerializer
from skiflux.services.activity import ActivityService
from skiflux.utils import AdminJWTAuthentication, APIResponse
from skiflux.utils.pagination import RecommendationPaginator

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


def _require_permission(admin, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


def _activity_queryset(request):
    queryset = ActivityLog.objects.select_related(
        "actor_user",
        "actor_admin",
        "subject_user",
        "subject_admin",
    )

    action_type = request.query_params.get("action_type")
    if action_type:
        queryset = queryset.filter(action_type=action_type)

    search = request.query_params.get("search", "").strip()
    if search:
        queryset = queryset.filter(description__icontains=search)

    return queryset


@extend_schema(
    summary="List Admin Activities",
    description="Returns a paginated list of recent platform activity logs.",
    parameters=[
        OpenApiParameter("action_type", str, required=False),
        OpenApiParameter("search", str, required=False),
        OpenApiParameter("page", int, required=False),
    ],
    responses={200: OpenApiResponse(response=ActivityLogSerializer(many=True))},
    tags=["Admin › Dashboard"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_activities(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    queryset = _activity_queryset(request)
    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(queryset, request)
    serializer = ActivityLogSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Activities retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Get Recent Admin Activities",
    description="Returns recent activity logs for the overview dashboard widget.",
    parameters=[
        OpenApiParameter(
            name="limit",
            type=int,
            required=False,
            description="Number of activities to return (default: 10, max: 50).",
        )
    ],
    responses={200: OpenApiResponse(response=ActivityLogSerializer(many=True))},
    tags=["Admin › Dashboard"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def recent_activities(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    try:
        limit = int(request.query_params.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    activities = ActivityService.get_dashboard_activities(limit=limit)
    serializer = ActivityLogSerializer(activities, many=True)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Recent activities retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Admin Activity Stats",
    responses={200: OpenApiResponse(response=ActivityStatsSerializer)},
    tags=["Admin › Dashboard"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def activity_stats(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    serializer = ActivityStatsSerializer(ActivityService.get_activity_stats())
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Activity stats retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get User Activities",
    description="Returns a paginated list of activity log entries for a specific user.",
    parameters=[
        OpenApiParameter(
            name="user_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="ID of the user whose activities are being retrieved.",
        ),
        OpenApiParameter("page", int, required=False),
    ],
    responses={200: OpenApiResponse(response=ActivityLogSerializer(many=True))},
    tags=["Admin > Learner"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_user_activities(request, user_id):
    try:
        _require_permission(request.user, Permission.USERS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    try:
        queryset = ActivityService.get_user_activity_feed(user_id)
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(queryset, request)
    serializer = ActivityLogSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="User activities retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )
