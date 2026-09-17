from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from skiflux.models import Episode, Permission
from skiflux.serializers import (
    AttachTasksSerializer,
    CreatorRegistrationSerializer,
    CreatorResendOTPSerializer,
    EpisodeCreateSerializer,
    EpisodeReuploadSerializer,
    EpisodeSerializer,
    SeasonCreateSerializer,
    SeasonWithStatsSerializer,
    UpdateTasksSerializer,
    VerifyEmailSerializer,
)
from skiflux.serializers.creator import (
    CreatorAnalyticsResponseSerializer,
    CreatorProfileResponseSerializer,
    CreatorProfileUpdateSerializer,
)
from skiflux.serializers.studio import (
    EpisodeTaskDetailSerializer,
    EpisodeUpdateSerializer,
    SeasonUpdateSerializer,
)
from skiflux.serializers.user import DeviceRegisterSerializer
from skiflux.services import StudioService
from skiflux.utils import (
    AdminJWTAuthentication,
    APIResponse,
    IsVerifiedCreator,
    get_private_media_url,
)
from skiflux.utils.pagination import RecommendationPaginator

studio_service = StudioService()


def _paginated_task_submissions_response(request, queryset, message: str):
    paginator = RecommendationPaginator()
    page = paginator.paginate_queryset(queryset, request)
    results = studio_service.serialize_task_submissions(page)
    return APIResponse(
        status="success",
        status_code=200,
        message=message,
        data={
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": results,
        },
    )


class _DummySerializer(serializers.Serializer):
    pass


class StudioViewSet(viewsets.ViewSet):
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = _DummySerializer

    def get_permissions(self):
        public_actions = [
            "register_creator",
            "verify_creator_email",
            "resend_creator_otp",
        ]
        # Actions that require authentication but not full verification
        auth_only_actions = [
            "update_profile",
            "profile",
            "episode_full_details",
            "get_episode_task",
            "get_task_submissions",
            "get_pending_task_submissions_for_creator",
            "get_episode_comments",
            "get_episode_stats",
            "register_device",
            "notifications",
            "mark_notification_read",
        ]

        current_action = getattr(self, "action", None)
        if current_action is None and hasattr(self, "action_map"):
            current_action = self.action_map.get(self.request.method.lower())

        if current_action in public_actions:
            return [AllowAny()]
        if current_action in auth_only_actions:
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsVerifiedCreator()]

    def get_authenticators(self):
        public_actions = [
            "register_creator",
            "verify_creator_email",
            "resend_creator_otp",
        ]

        current_action = getattr(self, "action", None)
        if current_action is None and hasattr(self, "action_map"):
            current_action = self.action_map.get(self.request.method.lower())

        if current_action in public_actions:
            return []
        return super().get_authenticators()

    @extend_schema(
        summary="Register Creator Account",
        request=CreatorRegistrationSerializer,
        tags=["Admin › Creator Profile"],
    )
    @action(detail=False, methods=["POST"])
    def register_creator(self, request):
        studio_service = StudioService()
        serializer = CreatorRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )

        try:
            data = serializer.validated_data.copy()
            data.pop("password_confirm", None)

            admin = studio_service.register_creator(**data)

            return APIResponse(
                status="success",
                status_code=status.HTTP_201_CREATED,
                message="Creator registered. OTP sent to email.",
                data={
                    "id": str(admin.id),
                    "username": admin.username,
                    "email": admin.email,
                    "role_type": admin.role_type,
                },
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

    @extend_schema(
        summary="Verify Creator Email",
        description="Verifies the Creator's email using the 6-digit "
        "OTP sent during signup.",
        request=VerifyEmailSerializer,
        responses={
            200: OpenApiResponse(
                description="Creator Email verified successfully. You can now login."
            )
        },
        tags=["Admin › Creator Profile"],
    )
    @action(detail=False, methods=["POST"])
    def verify_creator_email(self, request):
        studio_service = StudioService()
        serializer = VerifyEmailSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        try:
            studio_service.verify_email(**serializer.validated_data)
            return APIResponse(
                status="success",
                status_code=status.HTTP_200_OK,
                message="Creator Email verified successfully. You can now login.",
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

    @extend_schema(
        summary="Upload Video Episode",
        request={
            "multipart/form-data": EpisodeCreateSerializer,
        },
        tags=["Admin › Studio Content"],
        exclude=True,
    )
    @action(
        detail=False,
        methods=["POST"],
        parser_classes=[
            MultiPartParser,
            FormParser,
        ],
    )
    def create_episode(self, request):
        studio_service = StudioService()
        serializer = EpisodeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            episode = studio_service.create_episode(
                admin=request.user,
                season_id=str(serializer.validated_data["season_id"]),
                title=serializer.validated_data["title"],
                description=serializer.validated_data["description"],
                order=serializer.validated_data["order"],
                access_type=serializer.validated_data.get(
                    "access_type", Episode.AccessType.PAID
                ),
                video_file=serializer.validated_data.get("video_file"),
                thumbnail_file=serializer.validated_data.get("thumbnail_file"),
            )
            return APIResponse(
                status="success",
                status_code=status.HTTP_201_CREATED,
                message="Episode created. Video upload is processing.",
                data={"episode_id": str(episode.id)},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="Submit Episode for Admin Review",
        description=(
            "Creates an episode and starts the video upload. "
            "Once processing is complete the episode enters REVIEW status "
            "and must be approved by an admin before going live."
        ),
        request={
            "multipart/form-data": EpisodeCreateSerializer,
        },
        tags=["Admin › Studio Content"],
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="create-episode-for-review",
        parser_classes=[MultiPartParser, FormParser],
    )
    def create_episode_for_review(self, request):
        studio_service = StudioService()
        serializer = EpisodeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            episode = studio_service.create_episode_for_review(
                admin=request.user,
                season_id=str(serializer.validated_data["season_id"]),
                title=serializer.validated_data["title"],
                description=serializer.validated_data["description"],
                order=serializer.validated_data.get("order"),
                access_type=serializer.validated_data.get(
                    "access_type", Episode.AccessType.FREE
                ),
                video_file=serializer.validated_data.get("video_file"),
                thumbnail_file=serializer.validated_data.get("thumbnail_file"),
            )
            return APIResponse(
                status="success",
                status_code=status.HTTP_201_CREATED,
                message=(
                    "Episode submitted for review. "
                    "You will be notified once a decision has been made."
                ),
                data={"episode_id": str(episode.id)},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="Re-upload Episode Video",
        request={
            "multipart/form-data": EpisodeReuploadSerializer,
        },
        tags=["Admin › Studio Content"],
    )
    @action(
        detail=True,
        methods=["POST"],
        url_path="reupload-video",
        parser_classes=[MultiPartParser, FormParser],
    )
    def reupload_episode_video(self, request, pk=None):
        studio_service = StudioService()
        serializer = EpisodeReuploadSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            episode = studio_service.reupload_episode_video(
                admin=request.user,
                episode_id=str(pk),
                video_file=serializer.validated_data["video_file"],
                thumbnail_file=serializer.validated_data.get("thumbnail_file"),
            )
            return APIResponse(
                status="success",
                status_code=status.HTTP_200_OK,
                message="Video re-upload started. You will be notified by email.",
                data={"episode_id": str(episode.id)},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="Task Brief Builder",
        request=AttachTasksSerializer,
        tags=["Admin › Studio Content"],
    )
    @action(detail=True, methods=["POST"])
    def attach_task(self, request, pk=None):
        studio_service = StudioService()
        serializer = AttachTasksSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tasks = studio_service.attach_tasks(
                admin=request.user,
                episode_id=pk,
                project_task_data=serializer.validated_data.get("project_task"),
                assessment_task_data=serializer.validated_data.get("assessment_task"),
            )
            return APIResponse(
                status="success",
                status_code=status.HTTP_201_CREATED,
                message="Tasks attached.",
                data={
                    "project_task_id": str(tasks["project_task"].id)
                    if tasks["project_task"]
                    else None,
                    "assessment_task_id": str(tasks["assessment_task"].id)
                    if tasks["assessment_task"]
                    else None,
                },
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

    @extend_schema(
        summary="Update Tasks",
        request=UpdateTasksSerializer,
        tags=["Admin › Studio Content"],
    )
    @action(detail=True, methods=["PATCH"])
    def update_task(self, request, pk=None):
        studio_service = StudioService()
        serializer = UpdateTasksSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tasks = studio_service.update_tasks(
                admin=request.user,
                episode_id=pk,
                project_task_data=serializer.validated_data.get("project_task"),
                assessment_task_data=serializer.validated_data.get("assessment_task"),
            )
            return APIResponse(
                status="success",
                status_code=status.HTTP_200_OK,
                message="Tasks updated.",
                data={
                    "project_task_id": str(tasks["project_task"].id)
                    if tasks["project_task"]
                    else None,
                    "assessment_task_id": str(tasks["assessment_task"].id)
                    if tasks["assessment_task"]
                    else None,
                },
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

    @extend_schema(
        summary="Create a Season",
        request={
            "multipart/form-data": SeasonCreateSerializer,
        },
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["POST"], url_path="season/create")
    def create_season(self, request):
        studio_service = StudioService()
        serializer = SeasonCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            season = studio_service.create_season(
                admin=request.user, **serializer.validated_data
            )
            return APIResponse(
                status="success",
                status_code=status.HTTP_201_CREATED,
                message="Season created.",
                data={"id": str(season.id), "title": season.title},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="List My Seasons",
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["GET"], url_path="season/list")
    def list_seasons(self, request):
        studio_service = StudioService()
        seasons = studio_service.list_my_seasons(request.user)
        data = SeasonWithStatsSerializer(seasons, many=True).data
        return APIResponse(
            status="success",
            status_code=200,
            message="Seasons retrieved.",
            data=data,
        )

    @extend_schema(
        summary="Update a Season",
        request={
            "multipart/form-data": SeasonUpdateSerializer,
        },
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["PATCH"])
    def update_season(self, request, season_id=None):
        studio_service = StudioService()
        serializer = SeasonUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            season = studio_service.update_season(
                admin=request.user, season_id=season_id, **serializer.validated_data
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Season updated successfully.",
                data={"id": str(season.id), "title": season.title},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Unpublish a Season",
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["POST"])
    def unpublish_season(self, request, season_id=None):
        studio_service = StudioService()
        try:
            season = studio_service.unpublish_season(
                admin=request.user, season_id=season_id
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Season unpublished successfully.",
                data={"id": str(season.id), "title": season.title},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Remove a Season",
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["DELETE"])
    def remove_season(self, request, season_id=None):
        studio_service = StudioService()
        try:
            studio_service.remove_season(admin=request.user, season_id=season_id)
            return APIResponse(
                status="success",
                status_code=204,
                message="Season removed successfully.",
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Resend OTP to Creator Email",
        description="Resends the 6-digit OTP to the Creator's email address.",
        request=CreatorResendOTPSerializer,
        responses={200: OpenApiResponse(description="OTP sent successfully.")},
        tags=["Admin › Creator Profile"],
    )
    @action(detail=False, methods=["POST"])
    def resend_creator_otp(self, request):
        studio_service = StudioService()
        serializer = CreatorResendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        try:
            studio_service.resend_otp(**serializer.validated_data)
            return APIResponse(
                status="success",
                status_code=status.HTTP_200_OK,
                message="OTP Resent successfully.",
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

    @extend_schema(
        summary="List My Episodes",
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["GET"], url_path="episode/list")
    def list_episodes(self, request):
        studio_service = StudioService()
        episodes = studio_service.list_my_episodes(request.user)
        data = EpisodeSerializer(
            episodes,
            many=True,
            context={"request": request},
        ).data
        return APIResponse(
            status="success",
            status_code=200,
            message="Episodes retrieved.",
            data=data,
        )

    @extend_schema(
        summary="Update an Episode",
        request={
            "multipart/form-data": EpisodeUpdateSerializer,
        },
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["PATCH"])
    def update_episode(self, request, episode_id=None):
        studio_service = StudioService()
        serializer = EpisodeUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            episode = studio_service.update_episode(
                admin=request.user, episode_id=episode_id, **serializer.validated_data
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Episode updated successfully.",
                data={"id": str(episode.id), "title": episode.title},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Unpublish an Episode",
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["POST"])
    def unpublish_episode(self, request, episode_id=None):
        studio_service = StudioService()
        try:
            episode = studio_service.unpublish_episode(
                admin=request.user, episode_id=episode_id
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Episode unpublished successfully.",
                data={"id": str(episode.id), "title": episode.title},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Remove an Episode",
        tags=["Admin › Studio Content"],
    )
    @action(detail=False, methods=["DELETE"])
    def remove_episode(self, request, episode_id=None):
        studio_service = StudioService()
        try:
            studio_service.remove_episode(admin=request.user, episode_id=episode_id)
            return APIResponse(
                status="success",
                status_code=204,
                message="Episode removed successfully.",
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Get Episode Full Details",
        description=(
            "Returns episode, tasks, submissions and comments. "
            "Accessible to the episode owner or admins with CONTENT_MANAGE.",
        ),
        tags=["Admin › Studio Content"],
    )
    @action(detail=True, methods=["GET"], url_path="full-details")
    def episode_full_details(self, request, pk=None):
        studio_service = StudioService()
        try:
            data = studio_service.get_episode_full_details(
                admin=request.user, episode_id=str(pk)
            )
        except ValidationError as e:
            return APIResponse(status="error", status_code=400, message=e.detail)
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

        from skiflux.serializers.studio import (
            AssessmentSubmissionDetailSerializer,
            EpisodeCommentSerializer,
            EpisodeTaskSerializer,
            TaskSubmissionDetailSerializer,
        )

        episode_ser = EpisodeSerializer(
            data["episode"], context={"request": request}
        ).data
        tasks_ser = EpisodeTaskSerializer(data["tasks"], many=True).data
        submissions_ser = TaskSubmissionDetailSerializer(
            data["task_submissions"], many=True
        ).data
        assessment_ser = AssessmentSubmissionDetailSerializer(
            data["assessment_submissions"], many=True
        ).data
        comments_ser = EpisodeCommentSerializer(data["comments"], many=True).data

        return APIResponse(
            status="success",
            status_code=200,
            message="Episode full details retrieved.",
            data={
                "episode": episode_ser,
                "tasks": tasks_ser,
                "task_submissions": submissions_ser,
                "assessment_submissions": assessment_ser,
                "comments": comments_ser,
            },
        )

    @extend_schema(
        summary="Get Episode Stats",
        description=(
            "Returns total views, total submissions, "
            "completion rate and pending review count. "
            "Accessible to the episode owner or admins with CONTENT_MANAGE."
        ),
        tags=["Admin › Studio Content"],
    )
    @action(detail=True, methods=["GET"], url_path="get-episode-stats")
    def get_episode_stats(self, request, episode_id=None):
        studio_service = StudioService()
        try:
            data = studio_service.get_episode_stats(
                admin=request.user, episode_id=str(episode_id)
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Episode stats retrieved.",
                data=data,
            )
        except ValidationError as e:
            return APIResponse(status="error", status_code=400, message=e.detail)
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Complete/Update Creator Onboarding Profile",
        description="Enables a registered creator to upload "
        "their avatar, bio, and choose a unique username.",
        request={
            "multipart/form-data": CreatorProfileUpdateSerializer,
        },
        responses={200: OpenApiResponse(description="Profile successfully completed.")},
        tags=["Admin › Creator Profile"],
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="update-profile",
        parser_classes=[MultiPartParser, FormParser],
    )
    def update_profile(self, request):
        studio_service = StudioService()
        serializer = CreatorProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            admin = studio_service.update_creator_profile(
                admin=request.user, **serializer.validated_data
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Creator profile successfully updated. Onboarding complete.",
                data={
                    "id": str(admin.id),
                    "username": admin.username,
                    "bio": admin.bio,
                    "email": admin.email,
                    "display_name": admin.display_name,
                    "avatar_url": get_private_media_url(admin.avatar_public_id),
                },
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="Get Creator Profile",
        description=(
            "Get the current creator's profile with stats "
            "(subscribers, seasons, episodes, etc.)"
        ),
        tags=["Admin › Creator Profile"],
        responses={200: CreatorProfileResponseSerializer},
    )
    @action(detail=False, methods=["GET"], url_path="profile")
    def profile(self, request):
        try:
            studio_service = StudioService()
            data = studio_service.get_my_profile(request.user)
            serializer = CreatorProfileResponseSerializer(data)

            return APIResponse(
                status="success",
                status_code=200,
                message="Creator profile retrieved.",
                data=serializer.data,
            )
        except (ValidationError, AttributeError) as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=str(e),
            )

    @extend_schema(
        summary="Get Creator Stats",
        description=(
            "Get the current creator's analytics "
            "(episodes this month, followers growth, earnings, ratings, etc.)"
        ),
        tags=["Admin › Creator Profile"],
        responses={200: CreatorAnalyticsResponseSerializer},
    )
    @action(detail=False, methods=["GET"], url_path="stats")
    def stats(self, request):
        try:
            studio_service = StudioService()
            data = studio_service.get_my_stats(request.user)
            serializer = CreatorAnalyticsResponseSerializer(data)

            return APIResponse(
                status="success",
                status_code=200,
                message="Creator stats retrieved.",
                data=serializer.data,
            )
        except (ValidationError, AttributeError) as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=str(e),
            )

    @extend_schema(
        summary="Get Episode Task",
        description=(
            "Get task details with submission counts. "
            "Accessible to the episode owner or admins with CONTENT_MANAGE."
        ),
        tags=["Admin › Studio Content"],
    )
    @action(detail=True, methods=["GET"], url_path="tasks/(?P<task_id>[^/.]+)")
    def get_episode_task(self, request, pk=None, task_id=None):
        studio_service = StudioService()
        try:
            data = studio_service.get_episode_task(
                admin=request.user, episode_id=str(pk), task_id=str(task_id)
            )

            serializer = EpisodeTaskDetailSerializer(data)
            return APIResponse(
                status="success",
                status_code=200,
                message="Task details retrieved.",
                data=serializer.data,
            )
        except ValidationError as e:
            return APIResponse(status="error", status_code=400, message=e.detail)
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Get Task Submissions",
        description=(
            "Get paginated task submissions with SLA status. "
            "Can filter by status (pending, approved, rejected). "
            "Accessible to the episode owner or admins with CONTENT_MANAGE."
        ),
        tags=["Admin › Studio Content"],
        parameters=[
            OpenApiParameter(
                name="status",
                description="Filter by submission status",
                required=False,
                enum=["pending", "approved", "rejected"],
            ),
            OpenApiParameter(
                name="page", description="Page number", required=False, type=int
            ),
            OpenApiParameter(
                name="limit", description="Page size", required=False, type=int
            ),
        ],
    )
    @action(
        detail=True,
        methods=["GET"],
        url_path="tasks/(?P<task_id>[^/.]+)/submissions",
    )
    def get_task_submissions(self, request, pk=None, task_id=None):
        try:
            status_filter = request.query_params.get("status")
            queryset = studio_service.get_task_submissions_queryset(
                admin=request.user,
                episode_id=str(pk),
                task_id=str(task_id),
                status_filter=status_filter,
            )
            return _paginated_task_submissions_response(
                request,
                queryset,
                message="Task submissions retrieved.",
            )
        except ValidationError as e:
            return APIResponse(status="error", status_code=400, message=e.detail)
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Get Pending Task Submissions",
        description="Get paginated pending task submissions for the creator.",
        tags=["Admin › Creator Management"],
        parameters=[
            OpenApiParameter(
                name="page", description="Page number", required=False, type=int
            ),
            OpenApiParameter(
                name="limit", description="Page size", required=False, type=int
            ),
        ],
    )
    @action(detail=False, methods=["GET"], url_path="tasks/pending-submissions")
    def get_pending_task_submissions_for_creator(self, request, creator_id: str):
        """Get paginated pending task submissions for a selected creator."""
        if request.user.id != creator_id and not request.user.has_permission(
            Permission.CONTENT_MANAGE
        ):
            raise PermissionDenied(
                "You are neither the creator nor an admin with the "
                "CONTENT_MANAGE permission to access this endpoint."
            )
        try:
            queryset = studio_service.get_pending_task_submissions_queryset(
                creator_id=creator_id
            )
            return _paginated_task_submissions_response(
                request,
                queryset,
                message="Pending task submissions retrieved.",
            )
        except ValidationError as e:
            return APIResponse(status="error", status_code=400, message=e.detail)
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Reject a pending project task submission (owner/creator)",
        description="Rejects a submission for one of the creator's episodes. "
        "Requires rejection_reason.",
        tags=["Admin › Studio Content"],
    )
    @action(
        detail=True,
        methods=["POST"],
        url_path="tasks/(?P<task_id>[^/.]+)/submissions/(?P<submission_id>[^/.]+)/reject",
    )
    def reject_task_submission(
        self, request, pk=None, task_id=None, submission_id=None
    ):
        studio_service = StudioService()
        rejection_reason = (request.data or {}).get("rejection_reason", "")
        try:
            sub = studio_service.reject_task_submission(
                admin=request.user,
                episode_id=str(pk),
                task_id=str(task_id),
                submission_id=str(submission_id),
                rejection_reason=rejection_reason,
            )
            return APIResponse(
                status="success",
                status_code=status.HTTP_200_OK,
                message="Submission rejected.",
                data={"submission_id": str(sub.id), "status": sub.status},
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail if hasattr(e, "detail") else str(e),
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Get Episode Comments",
        description=(
            "Get paginated episode comments. "
            "Accessible to the episode owner or admins with CONTENT_MANAGE."
        ),
        tags=["Admin › Studio Content"],
        parameters=[
            OpenApiParameter(
                name="offset", description="Pagination offset", required=False
            ),
            OpenApiParameter(name="limit", description="Page size", required=False),
        ],
    )
    @action(detail=True, methods=["GET"], url_path="comments")
    def get_episode_comments(self, request, pk=None):
        studio_service = StudioService()
        try:
            offset = int(request.query_params.get("offset", 0))
            limit = int(request.query_params.get("limit", 20))

            data = studio_service.get_episode_comments(
                admin=request.user, episode_id=str(pk), offset=offset, limit=limit
            )
            from skiflux.serializers.studio import EpisodeCommentListSerializer

            serializer = EpisodeCommentListSerializer(data)
            return APIResponse(
                status="success",
                status_code=200,
                message="Comments retrieved.",
                data=serializer.data,
            )
        except ValidationError as e:
            return APIResponse(status="error", status_code=400, message=e.detail)
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Register Creator Device Token for Push Notifications",
        description=(
            "Register (or update) a mobile device push token for the authenticated "
            "creator/admin. "
            "Use the same endpoint pattern as learners. Tokens enable push for "
            "creator events "
            "(new submissions, episode decisions, withdrawals, etc)."
        ),
        request=DeviceRegisterSerializer,
        responses={201: OpenApiResponse(description="Device registered.")},
        tags=["Admin › Creator Profile"],
    )
    @action(detail=False, methods=["POST"], url_path="devices")
    def register_device(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            device = studio_service.register_device(
                admin_user=request.user,
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
        except ValidationError as e:
            return APIResponse(status="error", status_code=400, message=e.detail)
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="List this creator's persisted notifications "
        "(web portal bell / history)",
        description=(
            "Returns in-app notification history for the authenticated creator "
            "(new followers, "
            "new submissions on episodes, comments, revenue/view milestones, "
            "episode status changes, etc.). "
            "Same shape as the learner /me/notifications endpoint. "
            "Use unread_only, offset, limit, and follow next links."
        ),
        parameters=[
            OpenApiParameter(
                "offset", int, description="Pagination offset", required=False
            ),
            OpenApiParameter(
                "limit", int, description="Page size (max 100)", required=False
            ),
            OpenApiParameter(
                "unread_only", bool, description="Only unread items", required=False
            ),
        ],
        responses={200: OpenApiResponse(description="List of notifications.")},
        tags=["Admin › Creator Profile"],
    )
    @action(detail=False, methods=["GET"], url_path="notifications")
    def notifications(self, request):
        """Thin action for creators on web portal. Delegates to studio_service."""
        offset = int(request.query_params.get("offset", 0))
        limit = min(int(request.query_params.get("limit", 20)), 100)
        unread_only = request.query_params.get("unread_only", "false").lower() == "true"

        result = studio_service.get_notifications(
            admin_user=request.user, unread_only=unread_only, offset=offset, limit=limit
        )

        next_url = None
        if len(result.get("items", [])) == limit:
            next_params = request.query_params.copy()
            next_params["offset"] = str(offset + limit)
            next_url = request.build_absolute_uri() + "?" + next_params.urlencode()

        return APIResponse(
            status="success",
            status_code=200,
            message="Notifications retrieved.",
            data={
                "count": result.get("total", 0),
                "results": result.get("items", []),
                "next": next_url,
                "offset": offset,
                "limit": limit,
            },
        )

    @extend_schema(
        summary="Mark a creator notification as read",
        tags=["Admin › Creator Profile"],
    )
    @action(detail=True, methods=["POST"], url_path="read")
    def mark_notification_read(self, request, pk=None):
        """Mark read for this creator's notification (web portal)."""
        studio_service.mark_notification_read(
            admin_user=request.user, notification_id=pk
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Notification marked as read.",
        )
