import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError

from skiflux.serializers.studio import EpisodeSerializer
from skiflux.serializers.user import (
    AppPreferencesSerializer,
    BiometricsStatusSerializer,
    CreatorNotificationPreferenceSerializer,
    CreatorNotificationPreferenceUpdateSerializer,
    DeviceRegisterSerializer,
    LeaderboardResponseSerializer,
    NotificationListResponseSerializer,
    NotificationPreferencesSerializer,
    UpdateProfileSerializer,
    UserLeaderboardEntrySerializer,
    UserProfileSerializer,
    UserSubmissionSerializer,
    WatchHistoryItemSerializer,
)
from skiflux.models import User
from skiflux.services.profile_service import UserProfileService
from skiflux.services.content_service import ContentService
from skiflux.utils import APIResponse
from skiflux.utils.auth import JWTAuthentication
from skiflux.utils.episode_serializer import build_episode_serializer_context

logger = logging.getLogger(__name__)

skillworld_choices = [choice[0] for choice in User.Skillworld.choices]

_SKILLWORLD_PARAM = OpenApiParameter(
    "skillworld",
    str,
    description=f"Filter by skillworld: {', '.join(skillworld_choices)}",
    required=False,
    enum=skillworld_choices,
)
_PAGE_SIZE_PARAM = OpenApiParameter(
    "page_size", int, description="Items per page (max 50)", required=False
)


class ProfilePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


class UserProfileViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.profile_service = UserProfileService()
        self.content_service = ContentService()

    def _paginated_response(self, queryset, serializer_class, request):
        """Reusable pagination + response wrapper."""
        paginator = ProfilePagination()
        page = paginator.paginate_queryset(queryset, request)
        if serializer_class in (EpisodeSerializer, WatchHistoryItemSerializer):
            context = build_episode_serializer_context(request, page)
        else:
            context = {"request": request}
        serializer = serializer_class(page, many=True, context=context)

        return APIResponse(
            status="success",
            status_code=200,
            message="Data retrieved.",
            data={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.data,
            },
        )

    @extend_schema(
        summary="My Profile",
        description=(
            "Returns the authenticated user's full profile: identity, avatar, "
            "skillworld, Skillcoin balance, XP earned from tasks, leaderboard rank, "
            "and a 3-episode watch history preview."
        ),
        responses={
            200: OpenApiResponse(
                response=UserProfileSerializer,
                description="Profile payload inside standard envelope `data`.",
            )
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="profile")
    def profile(self, request):
        data = self.profile_service.get_profile(request.user)
        serializer = UserProfileSerializer(data, context={"request": request})
        return APIResponse(
            status="success",
            status_code=200,
            message="Profile retrieved.",
            data=serializer.data,
        )

    @extend_schema(
        summary="Update Profile",
        description=(
            "Update the authenticated user's profile. "
            "All fields are optional. "
            "Send as multipart/form-data if uploading an avatar."
        ),
        request={
            "multipart/form-data": UpdateProfileSerializer,
            "application/json": UpdateProfileSerializer,
        },
        responses={
            200: OpenApiResponse(
                response=UserProfileSerializer,
                description="Updated profile inside standard envelope `data`.",
            ),
            400: OpenApiResponse(description="Validation error."),
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["PATCH"], url_path="update")
    def update_profile(self, request):
        avatar_file = request.FILES.get("avatar")

        # handle both json and multipart
        data = (
            request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        )
        data.pop("avatar", None)

        for field in ["goal", "skillworld"]:
            value = data.get(field)

            if isinstance(value, str) and "," in value:
                values = [v.strip() for v in value.split(",") if v.strip()]

                if hasattr(data, "setlist"):
                    data.setlist(field, values)
                else:
                    data[field] = values

        serializer = UpdateProfileSerializer(data=data, partial=True)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )

        try:
            user = self.profile_service.update_profile(
                user=request.user,
                data=dict(serializer.validated_data),
                avatar_file=avatar_file,
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

        # return fresh profile
        profile_data = self.profile_service.get_profile(user)
        return APIResponse(
            status="success",
            status_code=200,
            message="Profile updated.",
            data=UserProfileSerializer(profile_data, context={"request": request}).data,
        )

    @extend_schema(
        summary="Watch History",
        description=(
            "Paginated list of episodes the user has watched, newest first. "
            "Filter by completion status and/or skillworld. "
            "DELETE without episode_id clears all history."
        ),
        parameters=[
            OpenApiParameter(
                "completed",
                bool,
                description="true = only completed, false = only in-progress",
                required=False,
            ),
            _SKILLWORLD_PARAM,
            _PAGE_SIZE_PARAM,
        ],
        responses={200: WatchHistoryItemSerializer(many=True)},
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET", "DELETE"], url_path="watch-history")
    def watch_history(self, request):
        if request.method == "DELETE":
            deleted_count = self.profile_service.clear_watch_history(request.user)
            return APIResponse(
                status="success",
                status_code=200,
                message="Watch history cleared.",
                data={"deleted_count": deleted_count},
            )

        completed_raw = request.query_params.get("completed")
        completed = None
        if completed_raw is not None:
            completed = completed_raw.lower() in ("true", "1")

        skillworld = request.query_params.get("skillworld") or None

        qs = self.profile_service.get_watch_history(
            user=request.user,
            completed=completed,
            skillworld=skillworld,
        )
        return self._paginated_response(qs, WatchHistoryItemSerializer, request)

    @extend_schema(
        summary="Delete Watch History Item",
        description="Remove a single episode from the user's watch history.",
        tags=["User › Profile"],
    )
    @action(
        detail=False,
        methods=["DELETE"],
        url_path="watch-history/(?P<episode_id>[^/.]+)",
    )
    def delete_watch_history_item(self, request, episode_id=None):
        try:
            self.profile_service.delete_watch_history_item(request.user, episode_id)
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=str(e.detail) if hasattr(e, "detail") else str(e),
            )
        return APIResponse(
            status="success",
            status_code=200,
            message="Watch history entry removed.",
        )

    @extend_schema(
        summary="Saved Videos",
        description="Paginated list of published episodes the user has saved.",
        parameters=[_SKILLWORLD_PARAM, _PAGE_SIZE_PARAM],
        responses={200: EpisodeSerializer(many=True)},
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="saved")
    def saved(self, request):
        skillworld = request.query_params.get("skillworld") or None
        qs = self.profile_service.get_saved_episodes(
            user=request.user,
            skillworld=skillworld,
        )
        return self._paginated_response(qs, EpisodeSerializer, request)

    @extend_schema(
        summary="Liked Videos",
        description="Paginated list of published episodes the user has liked.",
        parameters=[_SKILLWORLD_PARAM, _PAGE_SIZE_PARAM],
        responses={200: EpisodeSerializer(many=True)},
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="liked")
    def liked(self, request):
        skillworld = request.query_params.get("skillworld") or None
        qs = self.profile_service.get_liked_episodes(
            user=request.user,
            skillworld=skillworld,
        )
        return self._paginated_response(qs, EpisodeSerializer, request)

    @extend_schema(
        summary="My Submissions",
        description=(
            "Standalone paginated list of the authenticated user's task submissions "
            "(both project-based and assessment). Supports filtering by status "
            "(pending, approved, rejected, passed, failed), skillworld, and episode_id."
            "Uses cursor-style offset/limit pagination with next/previous "
            "links computed. This is the primary endpoint for mobile to "
            "retrieve user submissions list."
        ),
        parameters=[
            OpenApiParameter(
                "status",
                description="Filter by status: pending | approved "
                "| rejected | passed | failed",
                required=False,
            ),
            _SKILLWORLD_PARAM,
            OpenApiParameter(
                "episode_id",
                description="Filter submissions by specific episode (lesson) UUID",
                required=False,
            ),
            _PAGE_SIZE_PARAM,
            OpenApiParameter(
                "offset",
                int,
                description="Pagination offset (for cursor-style "
                "offset/limit pagination)",
                required=False,
            ),
            OpenApiParameter(
                "cursor",
                description="Cursor for pagination (offset value as cursor)",
                required=False,
            ),
        ],
        responses={200: UserSubmissionSerializer(many=True)},
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="submissions")
    def submissions(self, request):
        # View is thin orchestrator - extract params only, no business logic
        status = request.query_params.get("status") or None
        skillworld = request.query_params.get("skillworld") or None
        episode_id = request.query_params.get("episode_id") or None
        cursor = request.query_params.get("cursor")
        if cursor is not None:
            try:
                offset = int(cursor)
            except (ValueError, TypeError):
                offset = 0
        else:
            offset = int(request.query_params.get("offset", 0))
        limit = int(
            request.query_params.get("page_size")
            or request.query_params.get("limit", 20)
        )
        limit = min(limit, 50)

        data = self.profile_service.get_user_submissions(
            user=request.user,
            status=status,
            skillworld=skillworld,
            episode_id=episode_id,
            offset=offset,
            limit=limit,
        )

        serializer = UserSubmissionSerializer(
            data["results"], many=True, context={"request": request}
        )

        # Compute next/prev links (cursor-style using offset)
        base_url = request.build_absolute_uri(request.path)
        query = request.GET.copy()
        total = data["total_count"]
        curr_offset = data["offset"]
        curr_limit = data["limit"]

        next_url = None
        if curr_offset + curr_limit < total:
            query["offset"] = str(curr_offset + curr_limit)
            next_url = f"{base_url}?{query.urlencode()}"

        prev_url = None
        if curr_offset > 0:
            prev_offset = max(0, curr_offset - curr_limit)
            query["offset"] = str(prev_offset)
            prev_url = f"{base_url}?{query.urlencode()}"

        return APIResponse(
            status="success",
            status_code=200,
            message="User submissions retrieved.",
            data={
                "count": total,
                "next": next_url,
                "previous": prev_url,
                "results": serializer.data,
                "offset": curr_offset,
                "limit": curr_limit,
            },
        )

    @extend_schema(
        summary="Register Device Token for Push Notifications",
        description=(
            "Register (or update) a mobile device push token (FCM / equivalent) for the"
            "authenticated user. Call this from the mobile app on launch, after login, "
            "or when the token is refreshed. The backend will store it for later use "
            "in push notification triggers (task approvals, new episodes, etc.)."
        ),
        request=DeviceRegisterSerializer,
        responses={
            201: OpenApiResponse(description="Device registered successfully."),
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["POST"], url_path="devices")
    def register_device(self, request):
        """Thin view: extract data, delegate to service, return response."""
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device = self.profile_service.register_device(
            user=request.user,
            **serializer.validated_data,
        )

        return APIResponse(
            status="success",
            status_code=201,
            message="Device registered for push notifications.",
            data={
                "token": device.token,
                "platform": device.platform,
                "is_active": device.is_active,
                "suggested_topics": ["platform_announcements"],
            },
        )

    @extend_schema(
        summary="List my notifications",
        description="Persisted in-app notifications (announcements, "
        "reminders, followed creator updates, etc.). Supports cursor/offset "
        "pagination.",
        parameters=[
            OpenApiParameter(
                "offset", int, description="Pagination offset", required=False
            ),
            OpenApiParameter("limit", int, description="Page size", required=False),
            OpenApiParameter(
                "unread_only", bool, description="Only unread", required=False
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=NotificationListResponseSerializer,
                description="Notification list inside standard envelope `data`.",
            )
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="notifications")
    def notifications(self, request):
        """Thin view delegating to service."""
        offset = int(request.query_params.get("offset", 0))
        limit = min(int(request.query_params.get("limit", 20)), 100)
        unread_only = request.query_params.get("unread_only", "false").lower() == "true"

        result = self.profile_service.get_notifications(
            user=request.user, unread_only=unread_only, offset=offset, limit=limit
        )

        # compute next/prev like other paginated
        next_url = None
        if len(result["items"]) == limit:
            next_params = request.query_params.copy()
            next_params["offset"] = str(offset + limit)
            next_url = request.build_absolute_uri() + "?" + next_params.urlencode()

        return APIResponse(
            status="success",
            status_code=200,
            message="Notifications retrieved.",
            data={
                "count": result["total"],
                "results": result["items"],
                "next": next_url,
                "offset": offset,
                "limit": limit,
            },
        )

    @extend_schema(
        summary="Mark notification as read",
        tags=["User › Profile"],
    )
    @action(detail=True, methods=["POST"], url_path="read")
    def mark_notification_read(self, request, pk=None):
        self.profile_service.mark_notification_read(
            user=request.user, notification_id=pk
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Notification marked as read.",
        )

    @extend_schema(
        summary="Mark all notifications as read",
        description=(
            "Idempotently marks every unread notification for the authenticated "
            "user as read. Returns the number of rows updated."
        ),
        tags=["User › Profile"],
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="notifications/mark-all-read",
    )
    def mark_all_notifications_read(self, request):
        updated = self.profile_service.mark_all_notifications_read(user=request.user)
        return APIResponse(
            status="success",
            status_code=200,
            message="All notifications marked as read.",
            data={"updated_count": updated},
        )

    @extend_schema(
        summary="Leaderboard",
        description=(
            "Returns the ranked leaderboard of all learners. "
            "The current user's position is always included in the response "
            "even if they are not on the current page. "
            "Supports search by name or username and filter by level."
        ),
        parameters=[
            OpenApiParameter(
                "search",
                str,
                description="Search by name or username.",
                required=False,
            ),
            OpenApiParameter(
                "level",
                str,
                description=(
                    "Filter by level: novice | amateur | senior | expert | professional"
                ),
                required=False,
            ),
            _PAGE_SIZE_PARAM,
        ],
        responses={
            200: OpenApiResponse(
                response=LeaderboardResponseSerializer,
                description="Leaderboard page inside standard envelope `data`.",
            ),
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="leaderboard")
    def leaderboard(self, request):
        search = request.query_params.get("search", "").strip() or None
        level = request.query_params.get("level") or None

        result = self.profile_service.get_leaderboard(
            current_user=request.user,
            search=search,
            level=level,
        )

        paginator = ProfilePagination()
        page = paginator.paginate_queryset(result["queryset"], request)

        serializer = UserLeaderboardEntrySerializer(
            page,
            many=True,
            context={"request": request},
        )

        # find current user in current page first
        current_user_data = next(
            (entry for entry in serializer.data if entry["is_me"]),
            None,
        )

        # if not on this page, fall back to separate query
        if not current_user_data and result["current_user_entry"]:
            current_user_data = UserLeaderboardEntrySerializer(
                result["current_user_entry"],
                context={"request": request},
            ).data

        return APIResponse(
            status="success",
            status_code=200,
            message="Leaderboard retrieved.",
            data={
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "my_position": current_user_data,
                "results": serializer.data,
            },
        )

    @extend_schema(
        summary="Toggle Biometrics",
        description=(
            "Toggles biometric authentication on or off for this user. "
            "The actual biometric verification is handled entirely on the device — "
            "this endpoint only stores the user's preference."
        ),
        responses={
            200: OpenApiResponse(
                description="Biometrics toggled.",
                response=BiometricsStatusSerializer,
            ),
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["POST"], url_path="biometrics/toggle")
    def toggle_biometrics(self, request):
        data = self.profile_service.toggle_biometrics(request.user)
        enabled = data["biometrics_enabled"]
        return APIResponse(
            status="success",
            status_code=200,
            message=("Biometrics enabled." if enabled else "Biometrics disabled."),
            data=BiometricsStatusSerializer(data).data,
        )

    @extend_schema(
        summary="Get Biometrics Status",
        description="Returns whether biometric authentication is enabled for the user.",
        responses={
            200: OpenApiResponse(
                description="Biometrics status retrieved.",
                response=BiometricsStatusSerializer,
            ),
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="biometrics")
    def biometrics_status(self, request):
        data = self.profile_service.get_biometrics_status(request.user)
        return APIResponse(
            status="success",
            status_code=200,
            message="Biometrics status retrieved.",
            data=BiometricsStatusSerializer(data).data,
        )

    @extend_schema(
        summary="Get Notification Preferences",
        description="Returns the user's current notification preferences.",
        responses={
            200: OpenApiResponse(
                description="Preferences retrieved.",
                response=NotificationPreferencesSerializer,
            ),
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="notification-preferences")
    def get_notification_preferences(self, request):
        prefs = self.profile_service.get_notification_preferences(request.user)
        serializer = NotificationPreferencesSerializer(prefs)
        return APIResponse(
            status="success",
            status_code=200,
            message="Notification preferences retrieved.",
            data=serializer.data,
        )

    @extend_schema(
        summary="Update Notification Preferences",
        description=(
            "Update one or more notification preferences. "
            "Send only the fields you want to change."
        ),
        request=NotificationPreferencesSerializer,
        responses={
            200: OpenApiResponse(
                description="Preferences updated.",
                response=NotificationPreferencesSerializer,
            ),
        },
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["PATCH"], url_path="notification-preferences/update")
    def update_notification_preferences(self, request):
        serializer = NotificationPreferencesSerializer(
            data=request.data,
            partial=True,
        )
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )

        prefs = self.profile_service.update_notification_preferences(
            user=request.user,
            data=serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Notification preferences updated.",
            data=NotificationPreferencesSerializer(prefs).data,
        )

    @extend_schema(
        summary="Get App Preferences",
        description="Returns synced app settings (playback, downloads, language, etc.)",
        responses={200: AppPreferencesSerializer},
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="app-preferences")
    def get_app_preferences(self, request):
        prefs = self.profile_service.get_app_preferences(request.user)
        return APIResponse(
            status="success",
            status_code=200,
            message="App preferences retrieved.",
            data=AppPreferencesSerializer(prefs).data,
        )

    @extend_schema(
        summary="Update App Preferences",
        request=AppPreferencesSerializer,
        responses={200: AppPreferencesSerializer},
        tags=["User › Profile"],
    )
    @action(detail=False, methods=["PATCH"], url_path="app-preferences/update")
    def update_app_preferences(self, request):
        serializer = AppPreferencesSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        prefs = self.profile_service.update_app_preferences(
            user=request.user,
            data=serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="App preferences updated.",
            data=AppPreferencesSerializer(prefs).data,
        )

    @extend_schema(
        summary="Creator Notification Preference",
        description=(
            "GET returns current mode for a followed creator. "
            "PATCH updates mode: all | personalized | none."
        ),
        methods=["GET"],
        responses={200: CreatorNotificationPreferenceSerializer},
        tags=["User › Profile"],
    )
    @extend_schema(
        methods=["PATCH"],
        request=CreatorNotificationPreferenceUpdateSerializer,
        responses={200: CreatorNotificationPreferenceSerializer},
        tags=["User › Profile"],
    )
    @action(
        detail=False,
        methods=["GET", "PATCH"],
        url_path="creator-notification-preferences/(?P<creator_id>[^/.]+)",
    )
    def creator_notification_preference(self, request, creator_id=None):
        if request.method == "PATCH":
            serializer = CreatorNotificationPreferenceUpdateSerializer(
                data=request.data
            )
            if not serializer.is_valid():
                return APIResponse(
                    status="error",
                    status_code=400,
                    message=serializer.errors,
                )
            try:
                data = self.content_service.update_creator_notification_preference(
                    request.user,
                    creator_id,
                    serializer.validated_data["mode"],
                )
            except ValidationError as e:
                return APIResponse(
                    status="error",
                    status_code=404,
                    message=str(e.detail) if hasattr(e, "detail") else str(e),
                )
            return APIResponse(
                status="success",
                status_code=200,
                message="Creator notification preference updated.",
                data=CreatorNotificationPreferenceSerializer(data).data,
            )

        try:
            data = self.content_service.get_creator_notification_preference(
                request.user, creator_id
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=str(e.detail) if hasattr(e, "detail") else str(e),
            )
        return APIResponse(
            status="success",
            status_code=200,
            message="Creator notification preference retrieved.",
            data=CreatorNotificationPreferenceSerializer(data).data,
        )
