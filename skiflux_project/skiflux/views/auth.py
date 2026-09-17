from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
    authentication_classes,
    throttle_classes,
)
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

from skiflux.serializers.auth import (
    AuthTokenResponseSerializer,
    ChangePasswordSerializer,
    CompleteOnboardingSerializer,
    ForgotPasswordRequestSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshTokenResponseSerializer,
    RefreshTokenSerializer,
    ResendOTPSerializer,
    ResetPasswordConfirmSerializer,
    SignupSerializer,
    VerifyEmailSerializer,
    VerifyForgotPasswordCode,
)
from skiflux.services.auth_service import AuthService
from skiflux.utils import (
    APIResponse,
    ForgotPasswordRateThrottle,
    OTPResendRateThrottle,
    get_private_avatar_url,
)


@extend_schema(
    summary="Health Check",
    description="Returns 200 if the service is running.",
    responses={200: OpenApiResponse(description="Service is awake.")},
    tags=["Health"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message="Service is awake",
    )


@extend_schema(
    summary="Register a new user",
    description=(
        "Registers a new user account"
        "**Note:** Passwords must be 8+ characters"
        "and include uppercase, numbers, and symbols.."
    ),
    request=SignupSerializer,
    responses={
        201: OpenApiResponse(
            description="Account created successfully",
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def signup(request):
    auth_service = AuthService()
    serializer = SignupSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    try:
        validated_data = serializer.validated_data.copy()
        validated_data.pop("password_confirm", None)
        auth_service.signup(**validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_201_CREATED,
            message="Account created successfully. "
            "Please check your email for verification code",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Verify Email",
    description="Verifies the user's email using the 6-digit OTP sent during signup.",
    request=VerifyEmailSerializer,
    responses={
        200: OpenApiResponse(
            description="Email verified successfully. You can now login."
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def verify_email(request):
    auth_service = AuthService()
    serializer = VerifyEmailSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    try:
        auth_service.verify_email(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Email verified successfully. You can now login.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Login",
    description="Login a registered user.",
    request=LoginSerializer,
    responses={
        200: OpenApiResponse(
            response=AuthTokenResponseSerializer,
            description=(
                "Login successful. Token payload is returned inside the standard "
                "envelope `data` field."
            ),
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    auth_service = AuthService()
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    try:
        data = auth_service.login(request, **serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Login successful",
            data=data,
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Forgot Password",
    description="send otp to user email",
    request=ForgotPasswordRequestSerializer,
    responses={
        200: OpenApiResponse(
            description="Sends a reset code to user email if the email exists."
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ForgotPasswordRateThrottle])
def forgot_password(request):
    auth_service = AuthService()
    serializer = ForgotPasswordRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            message=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
        )

    try:
        auth_service.forgot_password(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="A reset code has been sent.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Reset Password",
    description="verify otp and reset password",
    request=ResetPasswordConfirmSerializer,
    responses={
        200: OpenApiResponse(
            description="Password has been reset successfully.",
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def reset_password(request):
    auth_service = AuthService()
    serializer = ResetPasswordConfirmSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            message=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
        )

    try:
        validated_data = serializer.validated_data.copy()
        validated_data.pop("confirm_new_password", None)
        auth_service.reset_password(**validated_data)
        return APIResponse(
            message="Password has been reset successfully.",
            status_code=status.HTTP_200_OK,
            status="success",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Refresh Access Token",
    description="Exchanges a valid refresh token for a new access token.",
    request=RefreshTokenSerializer,
    responses={
        200: OpenApiResponse(
            response=RefreshTokenResponseSerializer,
            description=(
                "Access token refreshed. Token payload is returned inside `data`."
            ),
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def token_refresh(request):
    auth_service = AuthService()
    serializer = RefreshTokenSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    try:
        tokens = auth_service.token_refresh(**serializer.validated_data)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Access token refreshed successfully",
            data=tokens,
        )
    except ValueError as e:
        return APIResponse(
            status="error",
            message=str(e),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


@extend_schema(
    summary="Verify email OTP",
    description="Verifies the 6-digit OTP sent during forgot password.",
    request=VerifyForgotPasswordCode,
    responses={
        200: OpenApiResponse(
            description="Password OTP verified successfully.",
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def verify_password_otp(request):
    auth_service = AuthService()
    serializer = VerifyForgotPasswordCode(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            message=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
        )

    try:
        auth_service.verify_password_otp(**serializer.validated_data)
        return APIResponse(
            message="Password OTP verified successfully.",
            status_code=status.HTTP_200_OK,
            status="success",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Resend Verification OTP",
    description="Resends the OTP to the user's email.",
    request=ResendOTPSerializer,
    responses={
        200: OpenApiResponse(
            description="A new verification code has been sent.",
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([OTPResendRateThrottle])
def resend_otp(request):
    auth_service = AuthService()
    serializer = ResendOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            message=serializer.errors,
            status_code=status.HTTP_400_BAD_REQUEST,
            status="error",
        )

    try:
        auth_service.resend_otp(**serializer.validated_data)
        return APIResponse(
            message="A new verification code has been sent.",
            status_code=status.HTTP_200_OK,
            status="success",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Logout",
    description="Logs the user out by blacklisting their refresh token.",
    request=LogoutSerializer,
    responses={200: OpenApiResponse(description="Logged out successfully.")},
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    auth_service = AuthService()
    serializer = LogoutSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    try:
        auth_service.logout(**serializer.validated_data)
        access_token = request.auth
        if access_token:
            from skiflux.utils import blacklist_token

            blacklist_token(access_token)
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Logged out successfully.",
        )
    except ValueError as e:
        return APIResponse(
            status="error",
            status_code=400,
            message=str(e),
        )


@extend_schema(
    summary="Complete Onboarding",
    description="Sets up the user's profile, goal, and skillworld."
    "Marks the user as onboarded.",
    request={
        "multipart/form-data": CompleteOnboardingSerializer,
    },
    responses={200: OpenApiResponse(description="Onboarding complete")},
    tags=["User › Profile"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def complete_onboarding(request):
    auth_service = AuthService()
    serializer = CompleteOnboardingSerializer(
        data=request.data,
    )
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    avatar_file = request.FILES.get("avatar")

    try:
        updated_user = auth_service.complete_onboarding(
            user_id=request.user.id,
            data=serializer.validated_data,
            avatar_file=avatar_file,
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Welcome to Skillflux!",
            data={
                "is_onboarded": updated_user.is_onboarded,
                "username": updated_user.username,
                "avatar_url": get_private_avatar_url(updated_user.avatar_url),
            },
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )


@extend_schema(
    summary="Change Password",
    description="Allows an authenticated user to change their password.",
    request=ChangePasswordSerializer,
    responses={
        200: OpenApiResponse(
            description="Password changed successfully.",
        )
    },
    tags=["User › Auth"],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    auth_service = AuthService()
    serializer = ChangePasswordSerializer(
        data=request.data,
        context={"request": request},
    )
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    try:
        auth_service.change_password(
            user=request.user,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return APIResponse(
            status="success",
            status_code=status.HTTP_200_OK,
            message="Password changed successfully.",
        )
    except ValidationError as e:
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=e.detail,
        )
