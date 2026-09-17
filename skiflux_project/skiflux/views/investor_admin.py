from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from skiflux.models import Permission
from skiflux.serializers.investor import (
    InvestorReviewFilterSerializer,
    InvestorReviewListSerializer,
)
from skiflux.services.investor_service import InvestorService
from skiflux.utils import AdminJWTAuthentication, APIResponse
from skiflux.utils.pagination import RecommendationPaginator

_INVESTOR_ADMIN_TAGS = ["Admin › Investor Reviews"]

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


def _require_permission(admin, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


@extend_schema(
    summary="List investor reviews",
    description=(
        "Returns paginated investor landing page submissions for internal review."
    ),
    parameters=[
        OpenApiParameter(
            name="email",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Filter submissions by investor email.",
        ),
        OpenApiParameter(
            name="page",
            type=int,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Page number for pagination.",
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Investor reviews retrieved.",
            response=InvestorReviewListSerializer(many=True),
        )
    },
    tags=_INVESTOR_ADMIN_TAGS,
    operation_id="admin_investor_reviews_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_investor_reviews(request):
    try:
        _require_permission(request.user, Permission.ANALYTICS_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    filter_serializer = InvestorReviewFilterSerializer(data=request.query_params)
    if not filter_serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=filter_serializer.errors,
        )

    service = InvestorService()
    qs = service.list_reviews(
        email=filter_serializer.validated_data.get("email") or None,
    )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)
    results = [service.serialize_review(review) for review in page]
    serializer = InvestorReviewListSerializer(results, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Investor reviews retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )
