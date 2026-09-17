import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from skiflux.models import PlatformAnnouncement
from skiflux.models.role import Permission
from skiflux.serializers import SeasonStudioStatsSerializer, StudioEpisodeSerializer
from skiflux.serializers.content import (
    ApproveTaskSubmissionSerializer,
    PlatformAnnouncementSerializer,
    RejectTaskSubmissionSerializer,
)
from skiflux.serializers.studio import (
    EpisodeCommentListSerializer,
    EpisodeCommentSerializer,
    EpisodeSerializer,
    EpisodeTaskSerializer,
    SeasonTaskListSerializer,
    TaskSubmissionDetailSerializer,
)
from skiflux.services.content_service import ContentService
from skiflux.utils import AdminJWTAuthentication, APIResponse
from skiflux.utils.pagination import RecommendationPaginator

logger = logging.getLogger(__name__)

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


def _require_permission(admin, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


@extend_schema(
    summary="Approve Task Submission",
    description="Approve a task submission and award Skillcoin cashback to the user.",
    request=ApproveTaskSubmissionSerializer,
    responses={200: OpenApiResponse(description="Submission approved.")},
    tags=["Admin › Content"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def approve_task_submission(request, submission_id: str):
    try:
        _require_permission(request.user, Permission.CONTENT_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    serializer = ApproveTaskSubmissionSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    content_service = ContentService()
    try:
        submission = content_service.approve_submission(
            admin=request.user,
            submission_id=str(submission_id),
            cashback_amount=serializer.validated_data.get("cashback_amount"),
            feedback=serializer.validated_data.get("feedback"),
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Submission approved and cashback awarded.",
            data={
                "submission_id": str(submission.id),
                "cashback_amount": str(submission.cashback_amount),
                "feedback": submission.feedback,
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
    summary="Get Task Submission For Review",
    description="Fetch a task submission with task, episode, season and user details.",
    responses={200: TaskSubmissionDetailSerializer},
    tags=["Admin › Content"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_task_submission(request, submission_id: str):
    content_service = ContentService()
    try:
        submission = content_service.get_submission_for_review(
            admin=request.user,
            submission_id=str(submission_id),
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Submission retrieved.",
            data=TaskSubmissionDetailSerializer(submission).data,
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
    summary="Reject Task Submission",
    description="Reject a task submission with a reason and optional feedback.",
    request=RejectTaskSubmissionSerializer,
    responses={200: TaskSubmissionDetailSerializer},
    tags=["Admin › Content"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def reject_task_submission(request, submission_id: str):
    try:
        _require_permission(request.user, Permission.CONTENT_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    serializer = RejectTaskSubmissionSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    content_service = ContentService()
    try:
        submission = content_service.reject_submission(
            admin=request.user,
            submission_id=str(submission_id),
            rejection_reason=serializer.validated_data["rejection_reason"],
            feedback=serializer.validated_data.get("feedback"),
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Submission rejected.",
            data=TaskSubmissionDetailSerializer(submission).data,
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
    summary="Get Episode Review Detail",
    description="Fetch an episode with tasks, submissions and comments for review.",
    tags=["Admin › Content"],
    responses={
        200: OpenApiResponse(
            description="Episode review detail with episode, tasks, "
            "submissions, comments."
        )
    },
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_episode_review_detail(request, episode_id: str):
    content_service = ContentService()
    try:
        data = content_service.get_episode_review_detail(
            episode_id=str(episode_id),
            admin=request.user,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Episode review detail retrieved.",
            data={
                "episode": EpisodeSerializer(
                    data["episode"], context={"request": request}
                ).data,
                "tasks": EpisodeTaskSerializer(data["tasks"], many=True).data,
                "task_submissions": TaskSubmissionDetailSerializer(
                    data["task_submissions"], many=True
                ).data,
                "comments": EpisodeCommentSerializer(data["comments"], many=True).data,
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
    summary="Get season stats based on the season id",
    description="Get season stats based on the season id",
    tags=["Admin › Content"],
    responses={200: OpenApiResponse(description="Season stats")},
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_season_stats(request, season_id: str):
    content_service = ContentService()
    stats = content_service.get_season_stats(season_id=season_id, admin=request.user)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Season stats retrieved successfully.",
        data=SeasonStudioStatsSerializer(stats).data,
    )


@extend_schema(
    summary="Get episodes in a season for admin view",
    description="Get paginated episodes in a season for admin view",
    parameters=[
        OpenApiParameter(
            name="page",
            type=int,
            description="Page number for pagination",
            location=OpenApiParameter.QUERY,
        ),
    ],
    tags=["Admin › Content"],
    responses={200: OpenApiResponse(description="Episodes in the season")},
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_episodes_in_season(request, season_id: str):
    content_service = ContentService()
    episodes = content_service.get_episodes_by_season(
        season_id=season_id, admin=request.user
    )

    paginator = RecommendationPaginator()
    paginated_episodes = paginator.paginate_queryset(episodes, request)
    serializer = StudioEpisodeSerializer(paginated_episodes, many=True)

    return paginator.get_paginated_response(
        serializer.data, message="Episodes retrieved successfully."
    )


@extend_schema(
    summary="Get tasks in a season",
    description="Get all tasks in a season for review.",
    tags=["Admin › Content"],
    responses={200: SeasonTaskListSerializer},
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_tasks_in_season(request, season_id: str):
    content_service = ContentService()
    try:
        data = content_service.get_tasks_by_season(
            season_id=season_id,
            admin=request.user,
            offset=int(request.query_params.get("offset", 0)),
            limit=int(request.query_params.get("limit", 50)),
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Season tasks retrieved successfully.",
            data=SeasonTaskListSerializer(data).data,
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
    summary="Get comments in a season",
    description="Get all comments in a season for review.",
    tags=["Admin › Content"],
    responses={200: EpisodeCommentListSerializer},
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_comments_in_season(request, season_id: str):
    content_service = ContentService()
    try:
        flagged = request.query_params.get("flagged")
        if flagged is not None:
            flagged = flagged.lower()
            if flagged not in {"true", "false"}:
                raise ValidationError({"flagged": "Must be true or false."})
            flagged = flagged == "true"

        data = content_service.get_comments_by_season(
            season_id=season_id,
            admin=request.user,
            flagged=flagged,
            offset=int(request.query_params.get("offset", 0)),
            limit=int(request.query_params.get("limit", 50)),
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Season comments retrieved successfully.",
            data=EpisodeCommentListSerializer(data).data,
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
    summary="Send Platform Announcement",
    description="Superadmin sends announcement to ALL users (learners + creators). "
    "Always delivered (ignores toggles). Supports text, emojis, optional image. "
    "Can be immediate or scheduled daily. Live WS update + push + in-app history.",
    request=PlatformAnnouncementSerializer,
    responses={201: OpenApiResponse(description="Announcement sent/broadcast.")},
    tags=["Admin › Platform"],
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def send_platform_announcement(request):
    try:
        _require_permission(request.user, Permission.CONTENT_MANAGE)
        if not request.user.is_super_admin:
            raise PermissionDenied("Only super admins can send platform announcements.")
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    serializer = PlatformAnnouncementSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    from skiflux.services.notification_service import NotificationService

    ann = PlatformAnnouncement.objects.create(
        created_by=request.user,
        title=serializer.validated_data["title"],
        body=serializer.validated_data["body"],
        image_public_id=serializer.validated_data.get("image_public_id"),
        send_type=serializer.validated_data.get("send_type", "immediate"),
        daily_send_time=serializer.validated_data.get("daily_send_time"),
        delivery_channel=serializer.validated_data.get(
            "delivery_channel", "foreground"
        ),
        audience=serializer.validated_data.get("audience") or "All users",
        is_active=True,
    )

    notif_service = NotificationService()
    sent_count = 0
    try:
        # Send immediately if immediate
        if ann.send_type == "immediate":
            sent_count = notif_service.send_platform_announcement(announcement=ann)
        else:
            sent_count = notif_service.send_platform_announcement(
                announcement=ann, send_push=False
            )  # or handle in task
    except Exception:
        logger.warning("Announcement send partial failure")

    return APIResponse(
        status="success",
        status_code=status.HTTP_201_CREATED,
        message="Platform announcement created and broadcast "
        "(live WS + push for immediate).",
        data={
            "announcement_id": str(ann.id),
            "title": ann.title,
            "send_type": ann.send_type,
            "recipients_notified": sent_count,
        },
    )


@extend_schema(
    summary="List Platform Announcements (admin)",
    tags=["Admin › Platform"],
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_platform_announcements(request):
    try:
        if not request.user.is_super_admin:
            raise PermissionDenied("Super admin only.")
    except PermissionDenied as e:
        return APIResponse(status="error", status_code=403, message=str(e))

    qs = PlatformAnnouncement.objects.all()[:50]
    data = [
        {
            "id": str(a.id),
            "title": a.title,
            "body": a.body[:200],
            "send_type": a.send_type,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat(),
        }
        for a in qs
    ]
    return APIResponse(
        status="success",
        status_code=200,
        message="Announcements list.",
        data=data,
    )
