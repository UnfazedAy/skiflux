from drf_spectacular.utils import OpenApiResponse, extend_schema, OpenApiParameter
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, parser_classes
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from skiflux.serializers import EpisodeTasksResponseSerializer, SubmitTasksSerializer
from skiflux.serializers.creator import (
    EpisodeRatingRequestSerializer,
    EpisodeRatingResponseSerializer,
    FollowedCreatorSerializer,
    PublicCreatorProfileSerializer,
    ToggleFollowResponseSerializer,
)
from skiflux.serializers.studio import (
    EpisodeActionSerializer,
    CommentActionSerializer,
    EpisodeCommentCreateSerializer,
    EpisodeCommentReplyCreateSerializer,
    EpisodeCommentSerializer,
    EpisodeCommentUpdateSerializer,
    EpisodeLikeResponseSerializer,
    EpisodePurchaseResponseSerializer,
    EpisodeSaveResponseSerializer,
    SubmitTasksMultipartSerializer,
    SubmitTasksJsonSerializer,
    EpisodePurchaseSerializer,
    EpisodeSerializer,
    SeasonListSerializer,
    TrackViewSerializer,
    WatchedEpisodeTaskListSerializer,
)
from skiflux.services.content_service import ContentService
from skiflux.services.recommendation_service import (
    RecommendationService,
)
from skiflux.utils import APIResponse
from skiflux.utils.auth import JWTAuthentication
from skiflux.utils.episode_serializer import build_episode_serializer_context

content_service = ContentService()
recommendation_service = RecommendationService()


class RecommendationPaginator(PageNumberPagination):
    page_size = 10
    page_size_query_param = "limit"
    max_page_size = 50
    page_query_param = "page"


class _DummySerializer(serializers.Serializer):
    pass


class CommentPaginator(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    page_size_query_max = 50


class ContentViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = _DummySerializer

    @extend_schema(
        summary="Track Episode View",
        description="Records a view event for an episode. "
        "Updates watch duration and completion status. "
        "Requires access to the episode.",
        request=TrackViewSerializer,
        responses={
            200: OpenApiResponse(description="View recorded. Empty `data` object.")
        },
        tags=["User › Content"],
    )
    @action(detail=False, methods=["POST"], url_path="track-view")
    def track_view(self, request):
        serializer = TrackViewSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            content_service.track_view(
                user=request.user,
                **serializer.validated_data,
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="View recorded.",
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="Purchase an Episode",
        description="Purchases a paid episode for the authenticated user. "
        "Free episodes do not require purchase.",
        request=EpisodePurchaseSerializer,
        responses={
            201: OpenApiResponse(
                response=EpisodePurchaseResponseSerializer,
                description="Purchase result inside standard envelope `data`.",
            )
        },
        tags=["User › Content"],
    )
    @action(detail=False, methods=["POST"], url_path="purchase")
    def purchase_episode(self, request):
        serializer = EpisodePurchaseSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            purchase = content_service.purchase_episode(
                user=request.user,
                episode_id=str(serializer.validated_data["episode_id"]),
            )
            return APIResponse(
                status="success",
                status_code=201,
                message="Episode purchased.",
                data={"episode_id": str(purchase.episode.id)},
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="Get Episode by ID",
        description=(
            "Returns a published episode when the learner has access: free episodes "
            "or paid episodes that have been purchased. Paid episodes not yet "
            "purchased return 403. Episode and season must both be published."
        ),
        responses={
            200: OpenApiResponse(
                response=EpisodeSerializer,
                description="Episode detail inside standard envelope `data`.",
            ),
            403: OpenApiResponse(description="Purchase required for paid episode."),
            404: OpenApiResponse(description="Episode not found."),
        },
        tags=["User › Content"],
    )
    def get_episode(self, request, episode_id=None):
        try:
            episode = content_service.get_learner_episode(
                user=request.user,
                episode_id=str(episode_id),
            )
            serializer = EpisodeSerializer(
                episode,
                context=build_episode_serializer_context(request, [episode]),
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Episode retrieved.",
                data=serializer.data,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=e.detail,
            )

    @extend_schema(
        summary="Get Recommendations",
        description="Returns a paginated, personalised list of published episodes",  # noqa: E501
        responses=EpisodeSerializer(many=True),
        tags=["User › Content"],
    )
    @action(detail=False, methods=["GET"], url_path="recommendations")
    def recommendations(self, request):
        seen_ids = request.query_params.getlist("seen_ids")
        page_number = int(request.query_params.get("page", 1))
        qs = recommendation_service.get_queryset_for_user(
            user=request.user, seen_ids=seen_ids
        )

        paginator = RecommendationPaginator()
        page = paginator.paginate_queryset(qs, request)

        # shuffle within the page so same-scored episodes
        # feel fresh without affecting cross-page stability
        if page_number == 1:
            import random

            random.shuffle(page)

        serializer = EpisodeSerializer(
            page,
            many=True,
            context=build_episode_serializer_context(request, page),
        )
        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Recommendations fetched.",
            data=data,
        )

    @extend_schema(
        summary="Get Episode Tasks",
        description="Retrieves the tasks available for an episode (questions do not "
        "include the correct_answer for users). Also includes the authenticated user's "
        "own submission status/results (my_project_submission, "
        "my_assessment_submissions) "
        "if any.",
        responses=EpisodeTasksResponseSerializer,
        tags=["User › Content"],
    )
    @action(
        detail=False, methods=["GET"], url_path="episodes/(?P<episode_id>[^/.]+)/tasks"
    )
    def get_episode_tasks(self, request, episode_id=None):
        try:
            tasks_data = content_service.get_episode_tasks(
                user=request.user, episode_id=episode_id
            )
            serializer = EpisodeTasksResponseSerializer(tasks_data)
            return APIResponse(
                status="success",
                status_code=200,
                message="Tasks retrieved.",
                data=serializer.data,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))
        except ValidationError as e:
            return APIResponse(status="error", status_code=404, message=e.detail)

    @extend_schema(
        summary="Get Tasks From Watched Episodes",
        description=(
            "Returns all tasks attached to videos the authenticated user has viewed, "
            "including the user's current task status."
        ),
        responses=WatchedEpisodeTaskListSerializer,
        tags=["User › Content"],
    )
    @action(detail=False, methods=["GET"], url_path="episodes/watched/tasks")
    def get_watched_episode_tasks(self, request):
        offset = int(request.query_params.get("offset", 0))
        limit = min(int(request.query_params.get("limit", 50)), 100)
        data = content_service.get_tasks_for_viewed_episodes(
            user=request.user,
            offset=offset,
            limit=limit,
        )
        serializer = WatchedEpisodeTaskListSerializer(instance=data)
        return APIResponse(
            status="success",
            status_code=200,
            message="Watched episode tasks retrieved.",
            data=serializer.data,
        )

    @extend_schema(
        summary="Submit Tasks",
        description=(
            "Submits project and/or assessment tasks for an episode.\n\n"
            "**Assessment answers:** select `application/json` and send "
            "`assessment_submission.answers` as a map of question UUID → "
            "`A`/`B`/`C`/`D`.\n\n"
            "**Project with link:** also use `application/json` with nested "
            "`project_submission`.\n\n"
            "**Project with file upload:** select `multipart/form-data` and send "
            "flat fields (`episode_id`, `submission_file`, optional `submission_text`)."
        ),
        request={
            "application/json": SubmitTasksJsonSerializer,
            "multipart/form-data": SubmitTasksMultipartSerializer,
        },
        tags=["User › Content"],
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="tasks/submit",
        parser_classes=[JSONParser, MultiPartParser, FormParser],
    )
    def submit_task(self, request):
        serializer = SubmitTasksSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            submissions = content_service.submit_tasks(
                user=request.user,
                episode_id=str(serializer.validated_data["episode_id"]),
                project_submission_data=serializer.validated_data.get(
                    "project_submission"
                ),
                assessment_submission_data=serializer.validated_data.get(
                    "assessment_submission"
                ),
            )
            return APIResponse(
                status="success",
                status_code=201,
                message="Tasks submitted.",
                data=submissions,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )

    @extend_schema(
        summary="Toggle Like Episode",
        description="Like or unlike an episode.",
        request=EpisodeActionSerializer,
        responses={
            200: OpenApiResponse(
                response=EpisodeLikeResponseSerializer,
                description="Like toggle result inside standard envelope `data`.",
            )
        },
        tags=["User › Content Interactions"],
    )
    @action(detail=False, methods=["POST"], url_path="like")
    def like_episode(self, request):
        serializer = EpisodeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_liked = content_service.toggle_like(
            user=request.user, **serializer.validated_data
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Episode liked." if is_liked else "Episode unliked.",
            data={"is_liked": is_liked},
        )

    @extend_schema(
        summary="Toggle Save Episode",
        description="Save or unsave an episode for later.",
        request=EpisodeActionSerializer,
        responses={
            200: OpenApiResponse(
                response=EpisodeSaveResponseSerializer,
                description="Save toggle result inside standard envelope `data`.",
            )
        },
        tags=["User › Content Interactions"],
    )
    @action(detail=False, methods=["POST"], url_path="save")
    def save_episode(self, request):
        serializer = EpisodeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_saved = content_service.toggle_save(
            user=request.user, **serializer.validated_data
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Episode saved." if is_saved else "Episode unsaved.",
            data={"is_saved": is_saved},
        )

    @extend_schema(
        summary="Mark Episode Not Interested",
        description=(
            "Permanently remove an episode from the user's recommendation feed."
        ),
        request=EpisodeActionSerializer,
        tags=["User › Content Interactions"],
    )
    @action(detail=False, methods=["POST"], url_path="not-interested")
    def not_interested_episode(self, request):
        serializer = EpisodeActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = content_service.mark_not_interested(
                user=request.user,
                episode_id=str(serializer.validated_data["episode_id"]),
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=400,
                message=e.detail,
            )
        message = (
            "Episode already removed from your feed."
            if result["already_marked"]
            else "Episode removed from your feed."
        )
        return APIResponse(
            status="success",
            status_code=200,
            message=message,
            data=result,
        )

    @extend_schema(
        summary="Add Comment to Episode",
        description="Adds a comment to a specific episode.",
        request={
            "multipart/form-data": EpisodeCommentCreateSerializer,
            "application/json": EpisodeCommentCreateSerializer,
        },
        tags=["User › Content Interactions"],
    )
    @action(detail=False, methods=["POST"], url_path="comment")
    @parser_classes(
        [
            __import__(
                "rest_framework.parsers", fromlist=["MultiPartParser"]
            ).MultiPartParser,
            __import__("rest_framework.parsers", fromlist=["FormParser"]).FormParser,
            __import__("rest_framework.parsers", fromlist=["JSONParser"]).JSONParser,
        ]
    )
    def add_comment(self, request):
        serializer = EpisodeCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = content_service.add_comment(
            user=request.user, **serializer.validated_data
        )
        return APIResponse(
            status="success",
            status_code=201,
            message="Comment added.",
            data=EpisodeCommentSerializer(comment, context={"request": request}).data,
        )

    @extend_schema(
        summary="Toggle Like Comment",
        description="Like or unlike a comment.",
        request=CommentActionSerializer,
        tags=["User › Content Interactions"],
    )
    def like_comment(self, request):
        serializer = CommentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_liked = content_service.toggle_comment_like(
            user=request.user, **serializer.validated_data
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Comment liked." if is_liked else "Comment unliked.",
            data={"is_liked": is_liked},
        )

    @extend_schema(
        summary="Delete Comment",
        description="Deletes a comment owned by the authenticated user.",
        tags=["User › Content Interactions"],
    )
    def delete_comment(self, request, comment_id=None):
        content_service.delete_comment(user=request.user, comment_id=comment_id)
        return APIResponse(
            status="success",
            status_code=200,
            message="Comment deleted.",
        )

    @extend_schema(
        summary="Edit Comment",
        description="Edits the text of a comment owned by the authenticated user.",
        request=EpisodeCommentUpdateSerializer,
        tags=["User › Content Interactions"],
    )
    def edit_comment(self, request, comment_id=None):
        serializer = EpisodeCommentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = content_service.edit_comment(
            user=request.user,
            comment_id=comment_id,
            text=serializer.validated_data["text"],
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Comment updated.",
            data=EpisodeCommentSerializer(comment, context={"request": request}).data,
        )

    @extend_schema(
        summary="Reply to Comment",
        description="Adds a reply to an existing comment.",
        request={
            "multipart/form-data": EpisodeCommentReplyCreateSerializer,
            "application/json": EpisodeCommentReplyCreateSerializer,
        },
        tags=["User › Content Interactions"],
    )
    @parser_classes(
        [
            __import__(
                "rest_framework.parsers", fromlist=["MultiPartParser"]
            ).MultiPartParser,
            __import__("rest_framework.parsers", fromlist=["FormParser"]).FormParser,
            __import__("rest_framework.parsers", fromlist=["JSONParser"]).JSONParser,
        ]
    )
    def reply_to_comment(self, request, comment_id=None):
        serializer = EpisodeCommentReplyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = content_service.reply_to_comment(
            user=request.user,
            parent_comment_id=comment_id,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=201,
            message="Reply added.",
            data=EpisodeCommentSerializer(comment, context={"request": request}).data,
        )

    @extend_schema(
        summary="Get Episode Comments",
        description="Retrieves all comments for a given episode.",
        responses=EpisodeCommentSerializer(many=True),
        tags=["User › Content Interactions"],
    )
    @action(detail=True, methods=["GET"], url_path="comments")
    def get_comments(self, request, pk=None):
        comments = content_service.get_comments(episode_id=pk)
        paginator = CommentPaginator()
        page = paginator.paginate_queryset(comments, request)

        serializer = EpisodeCommentSerializer(
            page,
            many=True,
            context={"request": request},
        )
        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Comments retrieved.",
            data=data,
        )

    @extend_schema(
        summary="List Published Seasons",
        description=(
            "Returns a paginated catalogue of published seasons for mobile browse/playlists. "  # noqa: E501
            "Each season includes an HTTP cover URL and published episode count."
        ),
        parameters=[
            OpenApiParameter(
                name="skillworld",
                description="The skillworld to filter seasons by",
                required=False,
                type=str,
            ),
        ],
        responses={200: SeasonListSerializer(many=True)},
        tags=["User › Content"],
    )
    @action(detail=False, methods=["GET"], url_path="seasons")
    def list_seasons(self, request):
        skillworld = request.query_params.get("skillworld") or None
        qs = content_service.get_published_seasons(skillworld=skillworld)
        paginator = RecommendationPaginator()
        page = paginator.paginate_queryset(qs, request)
        serializer = SeasonListSerializer(page, many=True)
        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Seasons retrieved.",
            data=data,
        )

    @extend_schema(
        summary="Get Season Episodes",
        description="Retrieves all published episodes in a season, paginated.",
        responses=EpisodeSerializer(many=True),
        tags=["User › Content"],
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="seasons/<uuid:season_id>/episodes",
    )
    def get_season_episodes(self, request, season_id=None):
        try:
            episodes = content_service.get_season_episodes(season_id=season_id)
            return APIResponse(
                status="success",
                status_code=200,
                message="Season episodes retrieved.",
                data=EpisodeSerializer(
                    episodes,
                    many=True,
                    context=build_episode_serializer_context(request, episodes),
                ).data,
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=e.detail,
            )

    @extend_schema(
        summary="Get Creator Public Profile",
        description=(
            "Returns public profile information for a creator, "
            "including follow state for the authenticated user."
        ),
        tags=["User › Creator"],
        responses={200: PublicCreatorProfileSerializer},
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="creators/(?P<creator_id>[^/.]+)",
    )
    def get_creator_profile(self, request, creator_id=None):
        try:
            data = content_service.get_public_creator_profile(request.user, creator_id)
            serializer = PublicCreatorProfileSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            return APIResponse(
                status="success",
                status_code=200,
                message="Creator profile retrieved.",
                data=serializer.validated_data,
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=str(e.detail) if hasattr(e, "detail") else str(e),
            )

    @extend_schema(
        summary="List Creator Published Seasons",
        description=(
            "Returns published seasons for a creator catalogue / playlists screen. "
            "Each season includes a ready-to-use HTTP `cover_url`."
        ),
        parameters=[
            OpenApiParameter(
                name="skillworld",
                description="Optional skillworld filter",
                required=False,
                type=str,
            ),
        ],
        responses={200: SeasonListSerializer(many=True)},
        tags=["User › Creator"],
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="creators/(?P<creator_id>[^/.]+)/seasons",
    )
    def get_creator_seasons(self, request, creator_id=None):
        try:
            skillworld = request.query_params.get("skillworld") or None
            qs = content_service.get_creator_published_seasons(
                creator_id=creator_id,
                skillworld=skillworld,
            )
            paginator = RecommendationPaginator()
            page = paginator.paginate_queryset(qs, request)
            serializer = SeasonListSerializer(page, many=True)
            data = {
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.data,
            }
            return APIResponse(
                status="success",
                status_code=200,
                message="Creator seasons retrieved.",
                data=data,
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=str(e.detail) if hasattr(e, "detail") else str(e),
            )

    @extend_schema(
        summary="List Creator Published Episodes",
        description=(
            "Returns published episodes for a creator catalogue screen. "
            "Includes per-user `is_purchased`, `is_locked`, and `skillcoin_price`."
        ),
        parameters=[
            OpenApiParameter(
                name="skillworld",
                description="Optional skillworld filter",
                required=False,
                type=str,
            ),
        ],
        responses={200: EpisodeSerializer(many=True)},
        tags=["User › Creator"],
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="creators/(?P<creator_id>[^/.]+)/episodes",
    )
    def get_creator_episodes(self, request, creator_id=None):
        try:
            skillworld = request.query_params.get("skillworld") or None
            qs = content_service.get_creator_published_episodes(
                creator_id=creator_id,
                skillworld=skillworld,
            )
            paginator = RecommendationPaginator()
            page = paginator.paginate_queryset(qs, request)
            serializer = EpisodeSerializer(
                page,
                many=True,
                context=build_episode_serializer_context(request, page),
            )
            data = {
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.data,
            }
            return APIResponse(
                status="success",
                status_code=200,
                message="Creator episodes retrieved.",
                data=data,
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=str(e.detail) if hasattr(e, "detail") else str(e),
            )

    @extend_schema(
        summary="Toggle Follow Creator",
        description="Follow or unfollow a creator. Returns current follow state.",  # noqa: E501
        tags=["User › Creator"],
        responses={200: ToggleFollowResponseSerializer},
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="creators/(?P<creator_id>[^/.]+)/follow",
    )
    def toggle_follow(self, request, creator_id=None):
        try:
            result = content_service.toggle_follow(request.user, creator_id)
            serializer = ToggleFollowResponseSerializer(data=result)
            serializer.is_valid(raise_exception=True)
            return APIResponse(
                status="success",
                status_code=200,
                message="Unfollowed successfully."
                if not result["is_following"]
                else "Followed successfully.",
                data=serializer.validated_data,
            )
        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(
                status="error",
                status_code=status_code,
                message=str(e),
            )

    @extend_schema(
        summary="Rate Episode",
        description="Submit or update a rating for a purchased episode.",
        tags=["User › Content Interactions"],
        request=EpisodeRatingRequestSerializer,
        responses={200: EpisodeRatingResponseSerializer},
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="episodes/(?P<episode_id>[^/.]+)/rate",
    )
    def rate_episode(self, request, episode_id=None):
        serializer = EpisodeRatingRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error", status_code=400, message=serializer.errors
            )

        try:
            rating = content_service.rate_episode(
                user=request.user,
                episode_id=episode_id,
                score=serializer.validated_data["score"],
                review=serializer.validated_data.get("review"),
            )
            response_serializer = EpisodeRatingResponseSerializer(rating)
            return APIResponse(
                status="success",
                status_code=200,
                message="Episode rated successfully.",
                data=response_serializer.data,
            )
        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(
                status="error",
                status_code=status_code,
                message=str(e),
            )

    @extend_schema(
        summary="Get Followed Creators",
        description="Retrieves a paginated list of creators the "
        "authenticated user is following.",
        responses=FollowedCreatorSerializer(many=True),
        tags=["User › Creator"],
    )
    @action(detail=False, methods=["GET"], url_path="following")
    def get_followed_creators(self, request):
        creators = content_service.get_followed_creators(user=request.user)
        paginator = RecommendationPaginator()
        page = paginator.paginate_queryset(creators, request)

        serializer = FollowedCreatorSerializer(page, many=True)
        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Followed creators retrieved.",
            data=data,
        )

    @extend_schema(
        summary="Get Latest Episodes from Followed Creators",
        description="Retrieves a paginated list of the latest published episodes "
        "from the creators the authenticated user is following.",
        responses=EpisodeSerializer(many=True),
        tags=["User › Content Interactions"],
    )
    @action(detail=False, methods=["GET"], url_path="episodes/following")
    def get_latest_followed_episodes(self, request):
        episodes = content_service.get_latest_followed_episodes(user=request.user)
        paginator = RecommendationPaginator()
        page = paginator.paginate_queryset(episodes, request)

        serializer = EpisodeSerializer(
            page,
            many=True,
            context=build_episode_serializer_context(request, page),
        )
        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Latest episodes from followed creators retrieved.",
            data=data,
        )
