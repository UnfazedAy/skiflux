from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from skiflux.serializers.episode_resource_serializers import (
    AddFileResourceSerializer,
    AddLinkResourceSerializer,
    EpisodeResourceSerializer,
    ReorderResourcesSerializer,
    UpdateLinkResourceSerializer,
)
from skiflux.services.episode_resource_service import EpisodeResourceService
from skiflux.utils import APIResponse
from skiflux.utils.auth import AdminJWTAuthentication, JWTAuthentication

_RESOURCE_TAGS_STUDIO = ["Studio › Episode Resources"]
_RESOURCE_TAGS_LEARNER = ["User › Episode Resources"]


class EpisodeResourceStudioViewSet(viewsets.ViewSet):
    """
    All resource management endpoints for creators.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_service(self):
        return EpisodeResourceService()

    @extend_schema(
        summary="List Episode Resources",
        description="Returns all resources attached to an episode owned by the creator",
        responses={
            200: OpenApiResponse(
                description="Resources retrieved.",
                response=EpisodeResourceSerializer(many=True),
            ),
            400: OpenApiResponse(description="Episode not found."),
        },
        tags=_RESOURCE_TAGS_STUDIO,
        operation_id="studio_episode_resources_list",
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="episodes/(?P<episode_id>[^/.]+)/resources",
    )
    def list_resources(self, request, episode_id=None):
        service = self.get_service()
        try:
            resources = service.get_resources(
                episode_id=episode_id,
                creator=request.user,
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

        serializer = EpisodeResourceSerializer(resources, many=True)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Resources retrieved.",
            data=serializer.data,
        )

    @extend_schema(
        summary="Add File Resource",
        description=(
            "Upload a file resource to an episode. "
            "Supported: PDF, Figma (.fig), ZIP, Images, DOC. Max 50MB. "
            "Use multipart/form-data."
        ),
        request={"multipart/form-data": AddFileResourceSerializer},
        responses={
            201: OpenApiResponse(
                description="File resource queued for upload.",
                response=EpisodeResourceSerializer(many=True),
            ),
            400: OpenApiResponse(description="Validation error."),
        },
        tags=_RESOURCE_TAGS_STUDIO,
        operation_id="studio_episode_resource_add_file",
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="episodes/(?P<episode_id>[^/.]+)/resources/files",
    )
    def add_files(self, request, episode_id=None):
        serializer = AddFileResourceSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        service = self.get_service()
        try:
            resources = service.add_file_resources(
                episode_id=episode_id,
                creator=request.user,
                files=serializer.validated_data["files"],
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

        return APIResponse(
            status="success",
            status_code=status.HTTP_201_CREATED,
            message="File uploaded and queued for processing.",
            data=EpisodeResourceSerializer(resources, many=True).data,
        )

    @extend_schema(
        summary="Add Link Resource",
        description="Add an external link resource to an episode.",
        request=AddLinkResourceSerializer,
        responses={
            201: OpenApiResponse(
                description="Link resource created.",
                response=EpisodeResourceSerializer(many=True),
            ),
            400: OpenApiResponse(description="Validation error."),
        },
        tags=_RESOURCE_TAGS_STUDIO,
        operation_id="studio_episode_resource_add_link",
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="episodes/(?P<episode_id>[^/.]+)/resources/link",
    )
    def add_links(self, request, episode_id=None):
        serializer = AddLinkResourceSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        service = self.get_service()
        try:
            resource = service.add_link_resources(
                episode_id=episode_id,
                creator=request.user,
                links=serializer.validated_data["links"],
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

        return APIResponse(
            status="success",
            status_code=status.HTTP_201_CREATED,
            message="Link resource added.",
            data=EpisodeResourceSerializer(resource, many=True).data,
        )

    @extend_schema(
        summary="Update Link Resource",
        description="Update the label or URL of an existing link resource.",
        request=UpdateLinkResourceSerializer,
        responses={
            200: OpenApiResponse(
                description="Link resource updated.",
                response=EpisodeResourceSerializer,
            ),
            400: OpenApiResponse(description="Validation error."),
        },
        tags=_RESOURCE_TAGS_STUDIO,
        operation_id="studio_episode_resource_update_link",
    )
    @action(
        detail=False,
        methods=["PATCH"],
        url_path="episodes/(?P<episode_id>[^/.]+)/resources/(?P<resource_id>[^/.]+)/link",
    )
    def update_link(self, request, episode_id=None, resource_id=None):
        serializer = UpdateLinkResourceSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        service = self.get_service()
        try:
            resource = service.update_link_resource(
                episode_id=episode_id,
                resource_id=resource_id,
                creator=request.user,
                label=serializer.validated_data.get("label"),
                url=serializer.validated_data.get("url"),
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Link resource updated.",
            data=EpisodeResourceSerializer(resource).data,
        )

    @extend_schema(
        summary="Delete Resource",
        description=(
            "Delete a resource from an episode. "
            "File resources are also removed from Cloudinary."
        ),
        responses={
            200: OpenApiResponse(description="Resource deleted."),
            400: OpenApiResponse(description="Resource not found."),
        },
        tags=_RESOURCE_TAGS_STUDIO,
        operation_id="studio_episode_resource_delete",
    )
    @action(
        detail=False,
        methods=["DELETE"],
        url_path="episodes/(?P<episode_id>[^/.]+)/resources/(?P<resource_id>[^/.]+)",
    )
    def delete_resource(self, request, episode_id=None, resource_id=None):
        service = self.get_service()
        try:
            service.delete_resource(
                episode_id=episode_id,
                resource_id=resource_id,
                creator=request.user,
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Resource deleted.",
        )

    @extend_schema(
        summary="Reorder Resources",
        description=(
            "Update the display order of resources for an episode. "
            "Pass all resource IDs with their new order values."
        ),
        request=ReorderResourcesSerializer,
        responses={
            200: OpenApiResponse(description="Resources reordered."),
            400: OpenApiResponse(description="Validation error."),
        },
        tags=_RESOURCE_TAGS_STUDIO,
        operation_id="studio_episode_resource_reorder",
    )
    @action(
        detail=False,
        methods=["PATCH"],
        url_path="episodes/(?P<episode_id>[^/.]+)/resources/reorder",
    )
    def reorder_resources(self, request, episode_id=None):
        serializer = ReorderResourcesSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        service = self.get_service()
        try:
            service.reorder_resources(
                episode_id=episode_id,
                creator=request.user,
                reorder_data=serializer.validated_data["resources"],
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Resources reordered.",
        )


class EpisodeResourceLearnerViewSet(viewsets.ViewSet):
    """
    Read-only resource access for learners.
    Only returns resources for episodes the learner has access to.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get Episode Resources",
        description=(
            "Returns all resources attached to an episode. "
            "Learner must have access to the episode (free or purchased)."
        ),
        responses={
            200: OpenApiResponse(
                description="Resources retrieved.",
                response=EpisodeResourceSerializer(many=True),
            ),
            400: OpenApiResponse(description="Episode not found."),
            403: OpenApiResponse(description="No access to this episode."),
        },
        tags=_RESOURCE_TAGS_LEARNER,
        operation_id="learner_episode_resources_list",
    )
    @action(
        detail=False,
        methods=["GET"],
        url_path="episodes/(?P<episode_id>[^/.]+)/resources",
    )
    def list_resources(self, request, episode_id=None):
        from skiflux.models.content import Episode
        from skiflux.services.studio_service import ContentAccessService

        try:
            episode = Episode.objects.get(id=episode_id)
        except Episode.DoesNotExist:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Episode not found.",
            )

        # check learner has access
        access_service = ContentAccessService()
        if not access_service.can_user_access_episode(request.user, episode):
            return APIResponse(
                status="error",
                status_code=status.HTTP_403_FORBIDDEN,
                message="You do not have access to this episode.",
            )

        service = EpisodeResourceService()
        try:
            resources = service.get_resources(episode_id=str(episode_id))
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=e.detail,
            )

        serializer = EpisodeResourceSerializer(resources, many=True)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Resources retrieved.",
            data=serializer.data,
        )
