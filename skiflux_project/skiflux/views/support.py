import logging
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
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from skiflux.models.support import SupportTicket
from skiflux.serializers.support_serializers import (
    AssignableAdminSerializer,
    AssignTicketSerializer,
    ReopenTicketSerializer,
    ResolveTicketSerializer,
    SatisfactionScoreSerializer,
    SupportStatsSerializer,
    SupportTicketDetailSerializer,
    SupportTicketListSerializer,
    TicketFilterSerializer,
    TicketMessageSerializer,
    TicketReplySerializer,
    SupportAgentStatsSerializer,
)
from skiflux.services.support_service import SupportService
from skiflux.utils.pagination import RecommendationPaginator
from skiflux.tasks.support import poll_support_inbox
from skiflux.models import AdminUser, Permission
from skiflux.utils import (
    APIResponse,
    AdminJWTAuthentication,
)

_SUPPORT_TAGS = ["Admin › Customer Support"]

_admin_auth = [AdminJWTAuthentication]
_admin_only = [IsAuthenticated]

logger = logging.getLogger(__name__)


def _require_permission(admin: AdminUser, codename: str):
    if not admin.has_permission(codename):
        raise PermissionDenied(f"You do not have the '{codename}' permission.")


@extend_schema(
    summary="Get Support Stats",
    description="Returns the top-level support dashboard stats.",
    responses={
        200: OpenApiResponse(
            description="Stats retrieved.",
            response=SupportStatsSerializer,
        )
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_stats",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_support_stats(request):
    try:
        _require_permission(request.user, Permission.SUPPORT_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    poll_support_inbox.delay()
    data = service.get_stats()
    serializer = SupportStatsSerializer(data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Support stats retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Support Agent Stats",
    description=(
        "Returns the top-level support dashboard stats for a specific assigned agent."
    ),
    responses={
        200: OpenApiResponse(
            description="Agent Stats retrieved.",
            response=SupportAgentStatsSerializer,
        )
    },
    tags=_SUPPORT_TAGS,
    operation_id="get_support_agent_stats",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_support_agent_stats(request):
    try:
        _require_permission(request.user, Permission.SUPPORT_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    poll_support_inbox.delay()
    data = service.get_agent_stats(request.user.id)
    serializer = SupportAgentStatsSerializer(data)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Support stats retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="List Support Tickets",
    description="Returns paginated support tickets with optional filters.",
    parameters=[
        OpenApiParameter(
            name="status",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=SupportTicket.Status.values,
        ),
        OpenApiParameter(
            name="category",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=SupportTicket.Category.values,
        ),
        OpenApiParameter(
            name="assigned_to_id",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Filter by assigned admin UUID.",
        ),
        OpenApiParameter(
            name="unassigned",
            type=bool,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Return only unassigned tickets.",
        ),
        OpenApiParameter(
            name="search",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Search by subject, email, name or ticket number.",
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Tickets retrieved.",
            response=SupportTicketListSerializer(many=True),
        )
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_list",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def list_support_tickets(request):
    try:
        _require_permission(request.user, Permission.SUPPORT_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    filter_serializer = TicketFilterSerializer(data=request.query_params)
    if not filter_serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=filter_serializer.errors,
        )

    filters = filter_serializer.validated_data
    service = SupportService()

    poll_support_inbox.delay()

    try:
        qs = service.get_ticket_list(
            status=filters.get("status"),
            category=filters.get("category"),
            assigned_to_id=filters.get("assigned_to_id"),
            search=filters.get("search", "").strip(),
            unassigned=filters.get("unassigned", False),
        )
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
        )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(qs, request)
    serializer = SupportTicketListSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Support tickets retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Get Support Ticket Detail",
    description="Returns a single ticket with full message thread.",
    responses={
        200: OpenApiResponse(
            description="Ticket retrieved.",
            response=SupportTicketDetailSerializer,
        ),
        404: OpenApiResponse(description="Ticket not found."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_detail",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_support_ticket(request, ticket_id):
    try:
        _require_permission(request.user, Permission.SUPPORT_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    try:
        ticket = service.get_ticket_detail(str(ticket_id))
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )

    serializer = SupportTicketDetailSerializer(ticket)
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Ticket retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Get Ticket Messages",
    description="Returns the full message thread for a ticket.",
    responses={
        200: OpenApiResponse(
            description="Messages retrieved.",
            response=TicketMessageSerializer(many=True),
        ),
        404: OpenApiResponse(description="Ticket not found."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_messages",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_ticket_messages(request, ticket_id):
    try:
        _require_permission(request.user, Permission.SUPPORT_VIEW)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    poll_support_inbox.delay()

    try:
        messages = service.get_messages(str(ticket_id))
    except Exception as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_404_NOT_FOUND,
            message=str(e),
        )

    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(messages, request)
    serializer = TicketMessageSerializer(page, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Ticket messages retrieved.",
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        },
    )


@extend_schema(
    summary="Assign Ticket",
    description="Assign a support ticket to an admin user.",
    request=AssignTicketSerializer,
    responses={
        200: OpenApiResponse(description="Ticket assigned."),
        400: OpenApiResponse(description="Ticket not found or already assigned."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_assign",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def assign_ticket(request, ticket_id):
    try:
        _require_permission(request.user, Permission.SUPPORT_ASSIGN)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    serializer = AssignTicketSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    service = SupportService()
    try:
        ticket = service.assign_ticket(
            ticket_id=str(ticket_id),
            admin_id=str(serializer.validated_data["admin_id"]),
            assigned_by=request.user,
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
        message="Ticket assigned.",
        data=SupportTicketDetailSerializer(ticket).data,
    )


@extend_schema(
    summary="Unassign Ticket",
    description="Remove the current assignee from a ticket.",
    responses={
        200: OpenApiResponse(description="Ticket unassigned."),
        400: OpenApiResponse(
            description="Ticket not assigned or cannot be unassigned."
        ),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_unassign",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def unassign_ticket(request, ticket_id):
    try:
        _require_permission(request.user, Permission.SUPPORT_ASSIGN)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    try:
        ticket = service.unassign_ticket(
            ticket_id=str(ticket_id),
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
        message="Ticket unassigned.",
        data=SupportTicketDetailSerializer(ticket).data,
    )


@extend_schema(
    summary="Resolve Ticket",
    description="Mark a support ticket as resolved.",
    request=ResolveTicketSerializer,
    responses={
        200: OpenApiResponse(description="Ticket resolved."),
        400: OpenApiResponse(description="Ticket not found or already resolved."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_resolve",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def resolve_ticket(request, ticket_id):
    try:
        _require_permission(request.user, Permission.SUPPORT_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    try:
        ticket = service.resolve_ticket(
            ticket_id=str(ticket_id),
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
        message="Ticket resolved.",
        data=SupportTicketDetailSerializer(ticket).data,
    )


@extend_schema(
    summary="Reopen Ticket",
    description="Reopen a resolved or closed ticket.",
    request=ReopenTicketSerializer,
    responses={
        200: OpenApiResponse(description="Ticket reopened."),
        400: OpenApiResponse(description="Ticket cannot be reopened."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_reopen",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def reopen_ticket(request, ticket_id):
    try:
        _require_permission(request.user, Permission.SUPPORT_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    try:
        ticket = service.reopen_ticket(
            ticket_id=str(ticket_id),
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
        message="Ticket reopened.",
        data=SupportTicketDetailSerializer(ticket).data,
    )


@extend_schema(
    summary="Get Assignable Admins",
    description="Returns admins who can be assigned to support tickets.",
    responses={
        200: OpenApiResponse(
            description="Assignable admins retrieved.",
            response=AssignableAdminSerializer(many=True),
        )
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_assignable_admins",
)
@api_view(["GET"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def get_assignable_admins(request):
    try:
        _require_permission(request.user, Permission.SUPPORT_ASSIGN)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    service = SupportService()
    admins = service.get_assignable_admins()
    serializer = AssignableAdminSerializer(admins, many=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Assignable admins retrieved.",
        data=serializer.data,
    )


@extend_schema(
    summary="Submit Satisfaction Score",
    description="Allows a user to rate their resolved support ticket 1-5.",
    request=SatisfactionScoreSerializer,
    responses={
        200: OpenApiResponse(description="Score submitted."),
        400: OpenApiResponse(description="Invalid score or ticket not resolved."),
    },
    tags=["Learner › Support"],
    operation_id="learner_support_satisfaction_score",
)
@api_view(["POST"])
def submit_satisfaction_score(request, ticket_id):
    serializer = SatisfactionScoreSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    service = SupportService()
    try:
        service.submit_satisfaction_score(
            ticket_id=str(ticket_id),
            score=serializer.validated_data["score"],
            user=request.user,
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
        message="Satisfaction score submitted. Thank you for your feedback.",
    )


@extend_schema(
    summary="Reply to Ticket",
    description=(
        "Send an email reply to the ticket sender from the dashboard. "
        "Supports optional file attachments. Use multipart/form-data."
    ),
    request={"multipart/form-data": TicketReplySerializer},
    responses={
        200: OpenApiResponse(
            description="Reply sent.",
            response=TicketMessageSerializer,
        ),
        400: OpenApiResponse(description="Ticket not found or cannot reply."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_ticket_reply",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def reply_to_ticket(request, ticket_id):
    try:
        _require_permission(request.user, Permission.SUPPORT_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    attachments = request.FILES.getlist("attachments")

    if attachments:
        data = request.data.copy()
        data.setlist("attachments", attachments)
    else:
        data = request.data

    serializer = TicketReplySerializer(data=data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    service = SupportService()
    try:
        message = service.reply_to_ticket(
            ticket_id=str(ticket_id),
            body=serializer.validated_data["body"],
            admin=request.user,
            attachments=serializer.validated_data.get("attachments", []),
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
        message="Reply sent.",
        data=TicketMessageSerializer(message).data,
    )


# ─────────────────────────────────────────
# Manual fetch trigger (dev/ops use)
# ─────────────────────────────────────────


@extend_schema(
    summary="Trigger Email Fetch",
    description=(
        "Manually triggers the IMAP email fetch task. "
        "Useful for testing and ops. Super admin only."
    ),
    responses={
        200: OpenApiResponse(description="Fetch triggered."),
        403: OpenApiResponse(description="Permission denied."),
    },
    tags=_SUPPORT_TAGS,
    operation_id="admin_support_trigger_fetch",
)
@api_view(["POST"])
@authentication_classes(_admin_auth)
@permission_classes(_admin_only)
def trigger_email_fetch(request):
    try:
        _require_permission(request.user, Permission.SUPPORT_MANAGE)
    except PermissionDenied as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_403_FORBIDDEN,
            message=str(e),
        )

    poll_support_inbox.delay()

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Email fetch task triggered.",
    )
