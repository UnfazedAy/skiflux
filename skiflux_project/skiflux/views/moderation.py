import csv

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)

from skiflux.models.moderation import ModerationActionLog
from skiflux.serializers.moderation import (
    CommentListSerializer,
    FlaggedCommentActionSerializer,
    LiftSuspensionSerializer,
    ModerationStatsSerializer,
    ReportCommentSerializer,
    UserSuspensionSerializer,
    ModerationActionLogSerializer,
    FlaggedCommentSerializer,
)
from skiflux.services.moderation_service import ModerationService
from skiflux.utils import (
    APIResponse,
    AdminJWTAuthentication,
)
from skiflux.models import AdminUser, Permission
from rest_framework.exceptions import PermissionDenied, ValidationError

from rest_framework.permissions import IsAuthenticated
from skiflux.utils.pagination import RecommendationPaginator

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]


_MODERATION_TAGS = ["Admin › Moderation"]


def _require_permission(admin: AdminUser, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


# ─────────────────────────────────────────
# Stats
# ─────────────────────────────────────────


@extend_schema(
    summary="Get Moderation Stats",
    description="Returns the four top-level moderation stats shown on the dashboard.",
    parameters=[
        OpenApiParameter(
            name="skillworld",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Filter stats by skillworld.",
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Moderation stats retrieved.",
            response=ModerationStatsSerializer,
        )
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_stats",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_moderation_stats(request):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = ModerationService()
    data = service.get_stats()
    serializer = ModerationStatsSerializer(data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Moderation stats retrieved.",
        data=serializer.data,
    )


# ─────────────────────────────────────────
# Flagged Content
# ─────────────────────────────────────────


@extend_schema(
    summary="List Flagged Comments",
    description="Returns all flagged comments pending moderation action.",
    parameters=[
        OpenApiParameter(
            name="skillworld",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Flagged comments retrieved.",
            response=FlaggedCommentSerializer(many=True),
        )
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_flagged_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_flagged_comments(request):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    skillworld = request.query_params.get("skillworld")
    service = ModerationService()
    qs = service.get_flagged_comments(skillworld=skillworld)

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)
    serializer = FlaggedCommentSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Flagged comments retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Perform Action on Flagged Comment",
    description=(
        "Perform a moderation action on a flagged comment. "
        "Actions: delete, warn, suspend, dismiss."
    ),
    request=FlaggedCommentActionSerializer,
    responses={
        200: OpenApiResponse(description="Action performed successfully."),
        400: OpenApiResponse(description="Invalid action or comment not found."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_flagged_action",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def flagged_comment_action(request, comment_id):
    try:
        _require_permission(request.user, Permission.MODERATION_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    serializer = FlaggedCommentActionSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    data = serializer.validated_data
    action = data["action"]
    service = ModerationService()

    try:
        if action == "delete":
            result = service.delete_comment(
                comment_id=comment_id,
                admin=request.user,
                reason=data.get("reason", ""),
            )

        elif action == "warn":
            result = service.warn_user(
                comment_id=comment_id,
                admin=request.user,
                category=data["category"],
                message=data["message"],
            )

        elif action == "suspend":
            result = service.suspend_user(
                comment_id=comment_id,
                admin=request.user,
                reason=data.get("reason", ""),
                duration_days=data.get("duration_days"),
            )

        elif action == "dismiss":
            result = service.dismiss_report(
                comment_id=comment_id,
                admin=request.user,
                reason=data.get("reason", ""),
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
        data=result,
    )


# ─────────────────────────────────────────
# All Comments
# ─────────────────────────────────────────


@extend_schema(
    summary="List All Comments",
    description="Returns all comments with search, filter and skillworld support.",
    parameters=[
        OpenApiParameter(
            name="search",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Search by username, email or comment text.",
        ),
        OpenApiParameter(
            name="filter",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=["all", "flagged", "deleted"],
            description="Filter comments by type.",
        ),
        OpenApiParameter(
            name="skillworld",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Comments retrieved.",
            response=CommentListSerializer(many=True),
        )
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_comments_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_all_comments(request):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    search = request.query_params.get("search", "").strip()
    filter_type = request.query_params.get("filter", "all")
    skillworld = request.query_params.get("skillworld")

    if filter_type not in ("all", "flagged", "deleted"):
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message="filter must be one of: all, flagged, deleted.",
        )

    service = ModerationService()
    qs = service.get_all_comments(
        search=search,
        filter_type=filter_type,
        skillworld=skillworld,
    )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)
    serializer = CommentListSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Comments retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Delete Comment",
    description="Directly delete a comment from the all comments view.",
    responses={
        200: OpenApiResponse(description="Comment deleted."),
        400: OpenApiResponse(description="Comment not found."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_comment_delete",
)
@api_view(["DELETE"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def delete_comment(request, comment_id):
    try:
        _require_permission(request.user, Permission.MODERATION_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = ModerationService()
    try:
        result = service.delete_comment(
            comment_id=comment_id,
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


# ─────────────────────────────────────────
# Suspensions
# ─────────────────────────────────────────


@extend_schema(
    summary="List Active Suspensions",
    description="Returns all currently active user suspensions.",
    parameters=[
        OpenApiParameter(
            name="skillworld",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Active suspensions retrieved.",
            response=UserSuspensionSerializer(many=True),
        )
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_suspensions_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_active_suspensions(request):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    skillworld = request.query_params.get("skillworld")
    service = ModerationService()
    qs = service.get_active_suspensions(skillworld=skillworld)

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)
    serializer = UserSuspensionSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Active suspensions retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Lift Suspension",
    description="Manually lift an active user suspension.",
    request=LiftSuspensionSerializer,
    responses={
        200: OpenApiResponse(description="Suspension lifted."),
        400: OpenApiResponse(description="Suspension not found or already lifted."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_suspension_lift",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def lift_suspension(request, suspension_id):
    try:
        _require_permission(request.user, Permission.MODERATION_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    serializer = LiftSuspensionSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    service = ModerationService()
    try:
        result = service.lift_suspension(
            suspension_id=str(suspension_id),
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


# ─────────────────────────────────────────
# Action Log
# ─────────────────────────────────────────


@extend_schema(
    summary="Get Action Log",
    description="Returns the full moderation action log, filterable by action type.",
    parameters=[
        OpenApiParameter(
            name="action_type",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=[
                ModerationActionLog.ActionType.COMMENT_DELETED,
                ModerationActionLog.ActionType.WARNING_ISSUED,
                ModerationActionLog.ActionType.SUSPENSION,
                ModerationActionLog.ActionType.REPORT_DISMISSED,
                ModerationActionLog.ActionType.SUSPENSION_LIFTED,
            ],
            description="Filter by action type.",
        ),
        OpenApiParameter(
            name="skillworld",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Action log retrieved.",
            response=ModerationActionLogSerializer(many=True),
        )
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_action_log",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_action_log(request):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    action_type = request.query_params.get("action_type")
    skillworld = request.query_params.get("skillworld")

    valid_types = ModerationActionLog.ActionType.values
    if action_type and action_type not in valid_types:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"Invalid action_type. Must be one of: {', '.join(valid_types)}",
        )

    service = ModerationService()
    qs = service.get_action_log(
        action_type=action_type,
        skillworld=skillworld,
    )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)
    serializer = ModerationActionLogSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Action log retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Export Action Log CSV",
    description="Downloads the moderation action log as a CSV file.",
    parameters=[
        OpenApiParameter(
            name="action_type",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
        OpenApiParameter(
            name="skillworld",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_action_log_export",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def export_action_log_csv(request):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    from django.http import HttpResponse

    action_type = request.query_params.get("action_type")
    skillworld = request.query_params.get("skillworld")

    service = ModerationService()
    qs = service.get_action_log(
        action_type=action_type,
        skillworld=skillworld,
    )

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="moderation_action_log.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Action",
            "Target User",
            "Content",
            "Performed By",
            "Reason",
            "Source",
            "Date",
        ]
    )

    for log in qs:
        writer.writerow(
            [
                log.get_action_type_display(),
                log.target_user.email if log.target_user else "",
                f"{log.comment.episode.title} · {log.comment.episode.season.title}"
                if log.comment and log.comment.episode
                else "",
                f"{log.performed_by.first_name} {log.performed_by.last_name}".strip()
                if log.performed_by
                else "Auto",
                log.reason,
                log.source,
                log.created_at.strftime("%b %d, %H:%M"),
            ]
        )

    return response


# ─────────────────────────────────────────
# Learner — report a comment
# ─────────────────────────────────────────


@extend_schema(
    summary="Report a Comment",
    description="Allows a learner to report a comment. Auto-flags after 3 reports.",
    request=ReportCommentSerializer,
    responses={
        200: OpenApiResponse(description="Comment reported."),
        400: OpenApiResponse(description="Already reported or comment not found."),
    },
    tags=["Learner › Comments"],
    operation_id="learner_report_comment",
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_comment(request, comment_id):
    serializer = ReportCommentSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    service = ModerationService()
    try:
        result = service.report_comment(
            comment_id=comment_id,
            reported_by=request.user,
            category=serializer.validated_data["category"],
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
    summary="Get Flagged Comments For User",
    description=(
        "Returns all flagged/reported comments authored by a specific user, "
        "including report counts, category breakdown, and like counts."
    ),
    parameters=[
        OpenApiParameter(
            name="user_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="ID of the user whose flagged comments are being retrieved.",
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Flagged comments retrieved.",
            response=FlaggedCommentSerializer(many=True),
        )
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_user_flagged_comments",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_user_flagged_comments(request, user_id):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = ModerationService()

    try:
        comments = service.get_flagged_comments_for_user(user_id)
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(comments, request)
    serializer = FlaggedCommentSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Flagged comments retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Flagged Comment For User",
    description=(
        "Returns a single flagged comment authored by the given user, "
        "including report counts, category breakdown, and like counts."
    ),
    parameters=[
        OpenApiParameter(
            name="user_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="ID of the user who authored the comment.",
        ),
        OpenApiParameter(
            name="comment_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="ID of the flagged comment.",
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Flagged comment retrieved.",
            response=FlaggedCommentSerializer,
        )
    },
    tags=_MODERATION_TAGS,
    operation_id="admin_moderation_user_flagged_comment_detail",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_user_flagged_comment(request, user_id, comment_id):
    try:
        _require_permission(request.user, Permission.MODERATION_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = ModerationService()

    try:
        comment = service.get_flagged_comment_for_user(user_id, comment_id)
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )

    serializer = FlaggedCommentSerializer(comment)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Flagged comment retrieved.",
        data=serializer.data,
    )
