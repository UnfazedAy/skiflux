from drf_spectacular.utils import OpenApiResponse, extend_schema, OpenApiParameter
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from skiflux.serializers.content import (
    EpisodeReviewActionSerializer,
    EpisodeReviewListSerializer,
    ContentApprovalStatsSerializer,
    ContentApprovalListSerializer,
)
from skiflux.serializers.admin import (
    BulkEpisodeReviewSerializer,
    VerificationStatsSerializer,
    VerificationEpisodeSerializer,
    VerificationFilterSerializer,
)
from skiflux.services.content_service import ContentService
from skiflux.utils import AdminJWTAuthentication, APIResponse
from skiflux.utils.pagination import RecommendationPaginator

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


@extend_schema(
    summary="List Episodes Under Review",
    description="Returns a paginated and serialized list of all "
    "episodes currently in REVIEW status, waiting for admin approval.",
    responses={
        200: OpenApiResponse(
            description="Paginated list of episodes under review.",
            response=EpisodeReviewListSerializer(many=True),
        )
    },
    tags=["Admin › Content"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_episodes_under_review(request):
    content_service = ContentService()
    try:
        episodes_qs = content_service.get_episodes_under_review_queryset(request.user)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(episodes_qs, request)

    if page is not None:
        serializer = EpisodeReviewListSerializer(
            page, many=True, context={"request": request}
        )
        response_data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Episodes under review retrieved.",
            data=response_data,
        )

    serializer = EpisodeReviewListSerializer(
        episodes_qs, many=True, context={"request": request}
    )
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Episodes under review retrieved.",
        data={
            "count": len(serializer.data),
            "next": None,
            "previous": None,
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Review Episode (Approve or Reject)",
    description=(
        "Approve or reject an episode that is in REVIEW status. "
        "An approval publishes the episode immediately. "
        "A rejection requires a reason, which is stored on the episode "
        "and emailed to the creator."
    ),
    request=EpisodeReviewActionSerializer,
    responses={200: OpenApiResponse(description="Review decision recorded.")},
    tags=["Admin › Content"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def review_episode(request, episode_id: str):
    serializer = EpisodeReviewActionSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    content_service = ContentService()
    try:
        episode = content_service.review_episode(
            admin=request.user,
            episode_id=str(episode_id),
            action=serializer.validated_data["action"],
            rejection_reason=serializer.validated_data.get("rejection_reason"),
        )

        new_status = episode.status
        message = (
            "Episode approved and published."
            if new_status == "published"
            else "Episode rejected. Creator has been notified."
        )

        response_data = {
            "episode_id": str(episode.id),
            "new_status": new_status,
        }
        if new_status == "rejected":
            response_data["rejection_reason"] = episode.rejection_reason

        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message=message,
            data=response_data,
        )
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Verification Stats",
    description="Returns live stats for the verification page — pending count, "
    "SLA breaches, avg wait and response time for the requesting admin.",
    responses={200: OpenApiResponse(description="Verification stats.")},
    tags=["Admin › Content"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def verification_stats(request):
    content_service = ContentService()
    try:
        stats = content_service.get_verification_stats(request.user)
        serializer = VerificationStatsSerializer(data=stats)
        serializer.is_valid(raise_exception=True)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Verification stats retrieved.",
            data=serializer.validated_data,
        )
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Verification Queue",
    description="Paginated list of episodes pending review, filterable by priority.",
    parameters=[VerificationFilterSerializer],
    responses={200: OpenApiResponse(description="Paginated verification queue.")},
    tags=["Admin › Content"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def verification_queue(request):
    filter_serializer = VerificationFilterSerializer(data=request.query_params)
    if not filter_serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=filter_serializer.errors,
        )

    content_service = ContentService()
    try:
        episodes = content_service.get_verification_queue(
            admin=request.user,
            priority=filter_serializer.validated_data.get("priority"),
            creator_id=filter_serializer.validated_data.get("creator_id"),
        )

        paginator = RecommendationPaginator()
        page = paginator.paginate_queryset(episodes, request)

        serializer = VerificationEpisodeSerializer(data=page, many=True)
        serializer.is_valid(raise_exception=True)

        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Verification queue retrieved.",
            data={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.validated_data,
            },
        )
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Bulk Review Episodes",
    description="Approve or reject multiple episodes at once. "
    "Only episodes in REVIEW status are processed; others are skipped.",
    request=BulkEpisodeReviewSerializer,
    responses={200: OpenApiResponse(description="Bulk review processed.")},
    tags=["Admin › Content"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def bulk_review_episodes(request):
    serializer = BulkEpisodeReviewSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    content_service = ContentService()
    try:
        results = content_service.bulk_review_episodes(
            admin=request.user,
            episode_ids=[str(i) for i in serializer.validated_data["episode_ids"]],
            action=serializer.validated_data["action"],
            rejection_reason=serializer.validated_data.get("reason"),
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message=f"{len(results['processed'])} episodes processed successfully.",
            data=results,
        )
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Content Approval Stats",
    description="Returns statistics for the content approval dashboard: pending count, "
    "approved today, rejected today, and average review time.",
    responses={200: OpenApiResponse(description="Content approval stats.")},
    tags=["Admin › Content"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def content_approval_stats(request):
    content_service = ContentService()
    try:
        stats = content_service.get_content_approval_stats(request.user)
        serializer = ContentApprovalStatsSerializer(data=stats)
        serializer.is_valid(raise_exception=True)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Content approval stats retrieved.",
            data=serializer.validated_data,
        )
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Content Approval List",
    description="Paginated list of episodes for content approval, filterable by status "
    "(awaiting_review, approved, rejected).",
    parameters=[
        OpenApiParameter(
            name="status",
            type=str,
            location=OpenApiParameter.QUERY,
            description="Optional Filter status: awaiting_review, approved, rejected",
        ),
        OpenApiParameter(
            name="skillworld",
            type=str,
            location=OpenApiParameter.QUERY,
            description="Optional filter by skillworld (e.g. 'web_development').",
        ),
    ],
    responses={200: OpenApiResponse(description="Paginated content approval list.")},
    tags=["Admin › Content"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def content_approval_list(request):
    status_filter = request.query_params.get("status")
    skillworld = request.query_params.get("skillworld")
    valid_filters = {None, "awaiting_review", "approved", "rejected"}
    if status_filter not in valid_filters:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid status filter. Use: awaiting_review, approved, rejected",
        )

    content_service = ContentService()
    try:
        episodes = content_service.get_content_approval_list(
            admin=request.user,
            status_filter=status_filter,
            skillworld=skillworld,
        )

        paginator = RecommendationPaginator()
        page = paginator.paginate_queryset(episodes, request)

        if page is not None:
            serializer = ContentApprovalListSerializer(page, many=True)
            return APIResponse(
                status="success",
                status_code=status.HTTP_200_OK,
                message="Content approval list retrieved.",
                data={
                    "count": paginator.page.paginator.count,
                    "next": paginator.get_next_link(),
                    "previous": paginator.get_previous_link(),
                    "results": serializer.data,
                },
            )

        serializer = ContentApprovalListSerializer(episodes, many=True)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Content approval list retrieved.",
            data={
                "count": len(serializer.data),
                "next": None,
                "previous": None,
                "results": serializer.data,
            },
        )
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )
