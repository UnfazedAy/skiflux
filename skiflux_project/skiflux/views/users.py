from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from skiflux.serializers.user import PublicUserProfileSerializer
from skiflux.services.profile_service import UserProfileService
from skiflux.utils import APIResponse, JWTAuthentication


@extend_schema(
    summary="Get Public User Profile",
    description=(
        "Returns a learner's public profile. Email is omitted. "
        "Deactivated and suspended users are not visible (404)."
    ),
    responses={
        200: OpenApiResponse(
            response=PublicUserProfileSerializer,
            description="Public profile inside standard envelope `data`.",
        ),
        404: OpenApiResponse(description="User not found."),
    },
    tags=["User › Profile"],
)
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_public_user_profile(request, user_id):
    service = UserProfileService()
    try:
        data = service.get_public_user_profile(user_id=str(user_id))
        serializer = PublicUserProfileSerializer(data, context={"request": request})
        return APIResponse(
            status="success",
            status_code=200,
            message="User profile retrieved.",
            data=serializer.data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=404,
            message=str(e.detail) if hasattr(e, "detail") else str(e),
        )


@extend_schema(
    summary="Get Public User Profile by Username",
    description=(
        "Same as GET /users/{user_id} but resolves by username. "
        "Deactivated and suspended users are not visible (404)."
    ),
    responses={
        200: OpenApiResponse(
            response=PublicUserProfileSerializer,
            description="Public profile inside standard envelope `data`.",
        ),
        404: OpenApiResponse(description="User not found."),
    },
    tags=["User › Profile"],
)
@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_public_user_profile_by_username(request, username):
    service = UserProfileService()
    try:
        data = service.get_public_user_profile(username=username)
        serializer = PublicUserProfileSerializer(data, context={"request": request})
        return APIResponse(
            status="success",
            status_code=200,
            message="User profile retrieved.",
            data=serializer.data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=404,
            message=str(e.detail) if hasattr(e, "detail") else str(e),
        )
