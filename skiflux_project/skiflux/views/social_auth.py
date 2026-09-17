import json
import urllib.parse

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from skiflux.serializers.auth import AuthTokenResponseSerializer
from skiflux.serializers import (
    AppleSocialAuthSerializer,
    FacebookSocialAuthSerializer,
    GoogleSocialAuthSerializer,
)
from skiflux.utils import (
    APIResponse,
    create_access_token,
    create_refresh_token,
    exchange_apple_code,
    exchange_facebook_code,
    exchange_google_code,
    get_apple_auth_url,
    get_facebook_auth_url,
    get_google_auth_url,
    get_or_create_social_user,
)


def _issue_social_tokens(user) -> dict:
    from skiflux.services.gamification_service import GamificationService

    GamificationService().process_daily_activity(user)
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_onboarded": user.is_onboarded,
            "username": user.username,
        },
    }


def _build_success_redirect(user) -> HttpResponseRedirect:
    """Redirects to the frontend deep link using a manual
    response to allow custom protocols."""
    tokens = _issue_social_tokens(user)
    params = urllib.parse.urlencode(
        {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "user_id": str(user.id),
            "email": user.email,
            "is_onboarded": user.is_onboarded,
            "username": user.username,
        }
    )
    url = f"{settings.SOCIAL_AUTH_SUCCESS_REDIRECT}?{params}"
    response = HttpResponse(status=302)
    response["Location"] = url
    return response


def _build_error_redirect(message: str) -> HttpResponseRedirect:
    """Redirects to the frontend with an error message."""
    params = urllib.parse.urlencode({"error": message})
    url = f"{settings.SOCIAL_AUTH_FAILURE_REDIRECT}?{params}"

    response = HttpResponse(status=302)
    response["Location"] = url
    return response


@extend_schema(
    summary="Initiate Google Login",
    description=(
        "Returns a redirect to Google's OAuth consent page. "
        "The frontend should open this URL in a browser or WebView."
    ),
    responses={
        302: OpenApiResponse(
            description="Redirects to Google consent page.",
        )
    },
    tags=["User › Social Auth"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def google_auth_init(request):
    """Redirects the user to Google's OAuth consent page."""
    return get_google_auth_url(request)


@extend_schema(
    summary="Google OAuth Callback",
    description=(
        "Google redirects here after the user consents. "
        "This exchanges the code, logs in/creates the user, "
        "and redirects to the frontend with tokens."
    ),
    responses={
        302: OpenApiResponse(
            description="Redirects to frontend with tokens.",
        )
    },
    tags=["User › Social Auth"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def google_auth_callback(request):
    """Handles Google's redirect back with the authorization code."""
    try:
        user_data = exchange_google_code(request)
        user = get_or_create_social_user("google", user_data)
        return _build_success_redirect(user)
    except Exception as e:
        return _build_error_redirect(str(e))


@extend_schema(
    summary="Initiate Facebook Login",
    description="Returns a redirect to Facebook's OAuth consent page.",
    responses={
        302: OpenApiResponse(
            description="Redirects to Facebook consent page.",
        )
    },
    tags=["User › Social Auth"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def facebook_auth_init(request):
    """Redirects the user to Facebook's OAuth consent page."""
    return get_facebook_auth_url(request)


@extend_schema(
    summary="Facebook OAuth Callback",
    description="Facebook redirects here after the user consents.",
    responses={
        302: OpenApiResponse(
            description="Redirects to frontend with tokens.",
        )
    },
    tags=["User › Social Auth"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def facebook_auth_callback(request):
    """Handles Facebook's redirect back with the authorization code."""
    try:
        user_data = exchange_facebook_code(request)
        user = get_or_create_social_user("facebook", user_data)
        return _build_success_redirect(user)
    except Exception as e:
        return _build_error_redirect(str(e))


@extend_schema(
    summary="Initiate Apple Login",
    description="Returns a redirect to Apple's OAuth consent page.",
    responses={
        302: OpenApiResponse(
            description="Redirects to Apple consent page.",
        )
    },
    tags=["User › Social Auth"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def apple_auth_init(request):
    """Redirects the user to Apple's Sign In page."""
    return HttpResponseRedirect(get_apple_auth_url())


@extend_schema(
    summary="Apple OAuth Callback",
    description=(
        "Apple POSTs here after the user consents (response_mode=form_post). "
        "Note: This must be a POST endpoint specifically because Apple posts"
        "the code via form."
    ),
    responses={
        302: OpenApiResponse(
            description="Redirects to frontend with tokens.",
        )
    },
    tags=["User › Social Auth"],
    exclude=True,
)
@api_view(["POST"])
@permission_classes([AllowAny])
def apple_auth_callback(request):
    """Handles Apple's POST callback with authorization
    code and optional user info."""
    try:
        code = request.data.get("code")
        if not code:
            raise ValueError("No authorization code received from Apple.")
        user_json = request.data.get("user", "{}")

        user_info = json.loads(user_json) if isinstance(user_json, str) else user_json
        name = user_info.get("name", {})
        first_name = name.get("firstName", "")
        last_name = name.get("lastName", "")

        user_data = exchange_apple_code(
            code, first_name=first_name, last_name=last_name
        )
        user = get_or_create_social_user("apple", user_data)
        return _build_success_redirect(user)
    except Exception as e:
        return _build_error_redirect(str(e))


@extend_schema(
    summary="Google Social Login For mobile",
    description="Authenticate with a Google ID Token from "
    "Google Sign-In. Returns access and refresh tokens.",
    request=GoogleSocialAuthSerializer,
    responses={
        200: OpenApiResponse(
            response=AuthTokenResponseSerializer,
            description=(
                "Google login successful. Token payload is returned inside `data`."
            ),
        )
    },
    tags=["User › Social Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def google_social_mobile_login(request):
    serializer = GoogleSocialAuthSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    user = serializer.validated_data["user"]
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Google login successful",
        data=_issue_social_tokens(user),
    )


@extend_schema(
    summary="Facebook Social Login For mobile",
    description="Authenticate with a Facebook User "
    + "Access Token from Facebook Login.",
    request=FacebookSocialAuthSerializer,
    responses={
        200: OpenApiResponse(
            description="Returns access_token and refresh_token.",
        )
    },
    tags=["User › Social Auth"],
    exclude=True,
)
@api_view(["POST"])
@permission_classes([AllowAny])
def facebook_social_mobile_login(request):
    serializer = FacebookSocialAuthSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    user = serializer.validated_data["user"]
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Facebook login successful",
        data=_issue_social_tokens(user),
    )


@extend_schema(
    summary="Apple Social Login For mobile",
    description="Authenticate with an Apple "
    + "Identity Token from Sign in with Apple.",
    request=AppleSocialAuthSerializer,
    responses={
        200: OpenApiResponse(
            response=AuthTokenResponseSerializer,
            description=(
                "Apple login successful. Token payload is returned inside `data`."
            ),
        )
    },
    tags=["User › Social Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def apple_social_mobile_login(request):
    serializer = AppleSocialAuthSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )
    user = serializer.validated_data["user"]
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Apple login successful",
        data=_issue_social_tokens(user),
    )
