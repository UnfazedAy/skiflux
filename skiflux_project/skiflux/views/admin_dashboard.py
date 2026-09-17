from drf_spectacular.utils import OpenApiResponse, extend_schema, OpenApiParameter
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from skiflux.models.role import Permission
from skiflux.serializers.admin import DashboardOverviewSerializer, UserGrowthSerializer
from skiflux.services.dashboard_service import DashboardService
from skiflux.utils import AdminJWTAuthentication, APIResponse

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


def _require_permission(admin, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


@extend_schema(
    summary="Get Admin Dashboard Overview",
    description=(
        "Returns high-level dashboard metrics for the admin portal, including "
        "learner growth, active creators, platform revenue in the last 24 hours, "
        "and pending verification priority."
    ),
    responses={
        200: OpenApiResponse(
            description="Dashboard overview retrieved successfully.",
            response=DashboardOverviewSerializer,
        )
    },
    tags=["Admin › Dashboard"],
    operation_id="admin_dashboard_overview",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_dashboard_overview(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    overview_data = DashboardService().get_overview()
    serializer = DashboardOverviewSerializer(overview_data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Dashboard overview retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get User Growth Chart",
    description=(
        "Returns monthly user registration counts with "
        "year-over-year percentage change. "
        "Pass `?months=N` to control the lookback window (default 6, max 12)."
    ),
    parameters=[
        OpenApiParameter(
            name="months",
            type=int,
            required=False,
            description=(
                "Number of months to look back for growth data  (default: 6, max: 12)."
            ),
        )
    ],
    responses={
        200: OpenApiResponse(
            description="User growth data retrieved successfully.",
            response=UserGrowthSerializer,
        )
    },
    tags=["Admin › Dashboard"],
    operation_id="admin_dashboard_user_growth",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_user_growth(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    try:
        months = int(request.query_params.get("months", 6))
    except (ValueError, TypeError):
        months = 6

    months = min(max(months, 1), 12)

    data = DashboardService().get_user_growth(months=months)
    serializer = UserGrowthSerializer(data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="User growth data retrieved.",
        data=serializer.data,
    )
