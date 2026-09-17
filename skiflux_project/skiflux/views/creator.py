from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError

from skiflux.serializers.creator import (
    CreatorListSerializer,
    CreatorOversightResponseSerializer,
    CreatorProfileResponseSerializer,
    OverrideEpisodeRequestSerializer,
    CreatorAnalyticsResponseSerializer,
    CreatorEpisodeSerializer,
    CreatorEpisodeListRequestSerializer,
    CreatorDirectoryItemSerializer,
    CreatorDirectoryRequestSerializer,
    CreatorDirectoryStatsSerializer,
)
from skiflux.services.creator_management_service import (
    CreatorManagementService,
)
from skiflux.utils import (
    AdminJWTAuthentication,
    APIResponse,
    HasCreatorManagePermission,
    HasCreatorViewPermission,
)
from skiflux.utils.pagination import (
    RecommendationPaginator,
    StandardResultsSetPagination,
)


def check_creator_gate(view_func):
    def _wrapped_view(request, *args, **kwargs):
        user = request.user
        if not getattr(user, "username", None) or not getattr(user, "bio", None):
            return APIResponse(
                message="Complete Your Creator Profile (username, bio, "
                "and avatar profile image) before proceeding.",
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
            )
        return view_func(request, *args, **kwargs)

    return _wrapped_view


management_service = CreatorManagementService()


class CreatorManagementViewSet(viewsets.ViewSet):
    authentication_classes = [AdminJWTAuthentication]

    def get_permissions(self):
        if self.action == "override_episode":
            return [HasCreatorManagePermission()]
        return [HasCreatorViewPermission()]

    @extend_schema(
        summary="List all Creators",
        description=(
            "Admin endpoint to retrieve a paginated"
            "list of all creators on the platform."
        ),
        tags=["Admin › Creator Management"],
        responses={200: CreatorListSerializer(many=True)},
    )
    def list(self, request):
        try:
            creators = management_service.list_creators(request.user)

            paginator = StandardResultsSetPagination()
            page = paginator.paginate_queryset(creators, request)

            if page is not None:
                data = [
                    {
                        "id": str(c.id),
                        "username": c.username,
                    }
                    for c in page
                ]
                return paginator.get_paginated_response(data)

            data = [
                {
                    "id": str(c.id),
                    "username": c.username,
                }
                for c in creators
            ]
            return APIResponse(
                status="success",
                status_code=200,
                message="Creators retrieved.",
                data=data,
            )
        except PermissionDenied as e:
            return APIResponse(status="error", status_code=403, message=str(e))

    @extend_schema(
        summary="Get Creator Oversight",
        description=(
            "Admin endpoint to fetch high-level"
            "oversight data (like episode count) for a specific creator."
        ),
        tags=["Admin › Creator Management"],
        responses={200: CreatorOversightResponseSerializer},
    )
    @action(detail=True, methods=["GET"])
    def oversight(self, request, pk=None):
        try:
            creator, episodes = management_service.get_creator_oversight(
                request.user, pk
            )
            data = {
                "creator_id": str(creator.id),
                "episodes_count": episodes.count(),
                "episodes": [
                    {
                        "id": str(e.id),
                        "title": e.title,
                        "status": e.status,
                    }
                    for e in episodes
                ],
            }
            serializer = CreatorOversightResponseSerializer(data=data)
            serializer.is_valid(raise_exception=True)

            return APIResponse(
                status="success",
                status_code=200,
                message="Content oversight retrieved.",
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
        summary="Get Creator Profile",
        description=(
            "Admin endpoint to fetch a creator's profile details and summary stats."
        ),
        tags=["Admin › Creator Management"],
        responses={200: CreatorProfileResponseSerializer},
    )
    @action(detail=True, methods=["GET"])
    def profile(self, request, pk=None):
        try:
            data = management_service.get_creator_profile(request.user, pk)
            serializer = CreatorProfileResponseSerializer(data=data)
            serializer.is_valid(raise_exception=True)

            return APIResponse(
                status="success",
                status_code=200,
                message="Creator profile retrieved.",
                data=serializer.data,
            )
        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(
                status="error",
                status_code=status_code,
                message=str(e),
            )

    @extend_schema(
        summary="Override Creator Episode",
        description=(
            "Admin endpoint to forcefully perform "
            "actions on a creator's episode (e.g., unpublish)."
        ),
        tags=["Admin › Creator Management"],
        request=OverrideEpisodeRequestSerializer,
        responses={200: None},
    )
    @action(detail=True, methods=["PATCH"])
    def override_episode(self, request, pk=None):
        serializer = OverrideEpisodeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error", status_code=400, message=serializer.errors
            )

        try:
            management_service.override_episode(
                creator_id=pk,
                episode_id=str(serializer.validated_data["episode_id"]),
                action=serializer.validated_data["action"],
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Override applied successfully.",
            )
        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(
                status="error",
                status_code=status_code,
                message=str(e),
            )

    @extend_schema(
        summary="Get Creator Analytics",
        description="Admin endpoint to fetch creator analytics.",
        tags=["Admin › Creator Management"],
        responses={200: CreatorAnalyticsResponseSerializer},
    )
    @action(detail=True, methods=["GET"])
    def analytics(self, request, pk=None):
        try:
            data = management_service.get_creator_analytics(str(pk))
            serializer = CreatorAnalyticsResponseSerializer(data=data)
            serializer.is_valid(raise_exception=True)

            return APIResponse(
                status="success",
                status_code=200,
                message="Creator analytics retrieved.",
                data=serializer.data,
            )
        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(
                status="error",
                status_code=status_code,
                message=str(e),
            )

    @extend_schema(
        summary="Get Creator Episodes",
        description=(
            "Returns paginated episodes for a creator.Optionally filter by status"
        ),
        tags=["Admin › Creator Management"],
        parameters=[CreatorEpisodeListRequestSerializer],
        responses={200: CreatorEpisodeSerializer(many=True)},
    )
    @action(detail=True, methods=["GET"], url_path="episodes")
    def creator_episodes(self, request, pk=None):
        # validate query params
        filter_serializer = CreatorEpisodeListRequestSerializer(
            data=request.query_params
        )
        if not filter_serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=filter_serializer.errors,
            )

        try:
            status_filter = filter_serializer.validated_data.get("status")
            episodes = management_service.get_creator_episodes(pk, status=status_filter)

            paginator = RecommendationPaginator()
            page = paginator.paginate_queryset(episodes, request)

            serializer = CreatorEpisodeSerializer(page, many=True)
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

        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(status="error", status_code=status_code, message=str(e))

    @extend_schema(
        summary="Creator Directory Stats",
        description="Top stats cards for the creator directory. Cached for 2 minutes.",
        tags=["Admin › Creator Management"],
        responses={200: CreatorDirectoryStatsSerializer},
    )
    @action(detail=False, methods=["GET"], url_path="directory/stats")
    def directory_stats(self, request):
        try:
            stats = management_service.get_directory_stats()
            serializer = CreatorDirectoryStatsSerializer(data=stats)
            serializer.is_valid(raise_exception=True)
            return APIResponse(
                status="success",
                status_code=200,
                message="Directory stats retrieved.",
                data=serializer.validated_data,
            )
        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(status="error", status_code=status_code, message=str(e))

    @extend_schema(
        summary="Creator Directory List",
        description="Paginated, filterable list of all creators.",
        tags=["Admin › Creator Management"],
        parameters=[CreatorDirectoryRequestSerializer],
        responses={200: CreatorDirectoryItemSerializer(many=True)},
    )
    @action(detail=False, methods=["GET"], url_path="directory")
    def directory(self, request):
        filter_serializer = CreatorDirectoryRequestSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=filter_serializer.errors,
            )

        try:
            creators = management_service.get_directory_list(
                search=filter_serializer.validated_data.get("search"),
                status=filter_serializer.validated_data.get("status"),
                date_from=filter_serializer.validated_data.get("date_from"),
                date_to=filter_serializer.validated_data.get("date_to"),
            )

            paginator = RecommendationPaginator()
            page = paginator.paginate_queryset(creators, request)
            serializer = CreatorDirectoryItemSerializer(page, many=True)
            data = {
                "count": paginator.page.paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.data,
            }
            return APIResponse(
                status="success",
                status_code=200,
                message="Creators directory retrieved.",
                data=data,
            )
        except (ValidationError, PermissionDenied) as e:
            status_code = 403 if isinstance(e, PermissionDenied) else 400
            return APIResponse(status="error", status_code=status_code, message=str(e))
