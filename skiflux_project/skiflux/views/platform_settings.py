from skiflux.serializers.platform_settings import (
    SystemContentConfigSerializer,
    SystemFeatureFlagConfigSerializer,
    SystemNotificationConfigSerializer,
    SystemSecurityConfigSerializer,
    SystemGamificationConfigSerializer,
)

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)

from skiflux.utils.permissions import IsSuperAdmin
from skiflux.services.platform_settings_service import PlatformSettingsService
from rest_framework.permissions import IsAuthenticated
from skiflux.utils import AdminJWTAuthentication, APIResponse

_admin_auth = [AdminJWTAuthentication]


@extend_schema(
    summary="Get or update platform content settings",
    description=(
        "Retrieve or update system content settings such as video size caps, "
        "allowed video formats, and season/episode limits."
    ),
    request=SystemContentConfigSerializer,
    responses={200: SystemContentConfigSerializer},
    tags=["Superadmin > Platform Settings"],
)
@api_view(["GET", "PATCH"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def manage_content_settings(request):
    platform_service = PlatformSettingsService()

    if request.method == "PATCH":
        serializer = SystemContentConfigSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        config = platform_service.update_content_config(
            admin=request.user,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform content settings updated successfully.",
            data=SystemContentConfigSerializer(config).data,
        )

    config = platform_service.get_content_config()
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Platform content settings retrieved successfully.",
        data=SystemContentConfigSerializer(config).data,
    )


@extend_schema(
    summary="Get or update platform notification settings",
    description=(
        "Retrieve or update system notification settings for platform events "
        "and email/sms notifications."
    ),
    request=SystemNotificationConfigSerializer,
    responses={200: SystemNotificationConfigSerializer},
    tags=["Superadmin > Platform Settings"],
)
@api_view(["GET", "PATCH"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def manage_notification_settings(request):
    platform_service = PlatformSettingsService()

    if request.method == "PATCH":
        serializer = SystemNotificationConfigSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        config = platform_service.update_notification_config(
            admin=request.user,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform notification settings updated successfully.",
            data=SystemNotificationConfigSerializer(config).data,
        )

    config = platform_service.get_notification_config()
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Platform notification settings retrieved successfully.",
        data=SystemNotificationConfigSerializer(config).data,
    )


@extend_schema(
    summary="Get or update platform security settings",
    description=(
        "Retrieve or update system security settings such as session timeout, "
        "failed login limits, and admin 2FA requirements."
    ),
    request=SystemSecurityConfigSerializer,
    responses={200: SystemSecurityConfigSerializer},
    tags=["Superadmin > Platform Settings"],
)
@api_view(["GET", "PATCH"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def manage_security_settings(request):
    platform_service = PlatformSettingsService()

    if request.method == "PATCH":
        serializer = SystemSecurityConfigSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        config = platform_service.update_security_config(
            admin=request.user,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform security settings updated successfully.",
            data=SystemSecurityConfigSerializer(config).data,
        )

    config = platform_service.get_security_config()
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Platform security settings retrieved successfully.",
        data=SystemSecurityConfigSerializer(config).data,
    )


@extend_schema(
    summary="Get or update platform feature flag settings",
    description=(
        "Retrieve or update system feature flag settings for platform capabilities."
    ),
    request=SystemFeatureFlagConfigSerializer,
    responses={200: SystemFeatureFlagConfigSerializer},
    tags=["Superadmin > Platform Settings"],
)
@api_view(["GET", "PATCH"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def manage_feature_flag_settings(request):
    platform_service = PlatformSettingsService()

    if request.method == "PATCH":
        serializer = SystemFeatureFlagConfigSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        config = platform_service.update_feature_flag_config(
            admin=request.user,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform feature flag settings updated successfully.",
            data=SystemFeatureFlagConfigSerializer(config).data,
        )

    config = platform_service.get_feature_flag_config()
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Platform feature flag settings retrieved successfully.",
        data=SystemFeatureFlagConfigSerializer(config).data,
    )


@extend_schema(
    summary="Get or update platform gamification settings",
    description=(
        "Retrieve or update system gamification settings for platform levels, "
        "xp requirements, and streaks."
    ),
    request=SystemGamificationConfigSerializer,
    responses={200: SystemGamificationConfigSerializer},
    tags=["Superadmin > Platform Settings"],
)
@api_view(["GET", "PATCH"])
@authentication_classes(_admin_auth)
@permission_classes([IsAuthenticated, IsSuperAdmin])
def manage_gamification_settings(request):
    platform_service = PlatformSettingsService()

    if request.method == "PATCH":
        serializer = SystemGamificationConfigSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=status.HTTP_400_BAD_REQUEST,
                message=serializer.errors,
            )

        config = platform_service.update_gamification_config(
            admin=request.user,
            **serializer.validated_data,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Platform gamification settings updated successfully.",
            data=SystemGamificationConfigSerializer(config).data,
        )

    config = platform_service.get_gamification_config()
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Platform gamification settings retrieved successfully.",
        data=SystemGamificationConfigSerializer(config).data,
    )
