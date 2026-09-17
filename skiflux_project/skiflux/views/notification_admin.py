from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from skiflux.models.role import Permission
from skiflux.serializers.content import (
    NotificationHistoryItemSerializer,
    NotificationStatsSerializer,
    PaginatedNotificationHistorySerializer,
)
from skiflux.services.notification_service import NotificationService
from skiflux.utils import AdminJWTAuthentication, APIResponse
from skiflux.utils.pagination import RecommendationPaginator

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


def _require_permission(admin, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


@extend_schema(
    summary="Notification Stats",
    description=(
        "Returns aggregate notification delivery stats for the admin analytics "
        "dashboard."
    ),
    responses={200: OpenApiResponse(response=NotificationStatsSerializer)},
    tags=["Admin › Dashboard"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def notification_stats(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    stats = NotificationService().get_admin_notification_stats()
    serializer = NotificationStatsSerializer(stats)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Notification stats retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Notification History",
    description=(
        "Returns grouped notification history derived from notification rows."
    ),
    parameters=[
        OpenApiParameter(
            name="type",
            description="Filter by delivery type",
            required=False,
            enum=["all", "foreground", "background", "scheduled"],
        ),
        OpenApiParameter(name="page", type=int, required=False),
        OpenApiParameter(name="limit", type=int, required=False),
    ],
    responses={200: OpenApiResponse(response=PaginatedNotificationHistorySerializer)},
    tags=["Admin › Dashboard"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def notification_history(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    delivery_filter = request.query_params.get("type", "all")
    if delivery_filter == "all":
        delivery_filter = None

    service = NotificationService()
    queryset = service.get_admin_notification_history_queryset(delivery_filter)
    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(queryset, request)
    results = service.serialize_notification_history_rows(page)
    serializer = NotificationHistoryItemSerializer(results, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Notification history retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )
