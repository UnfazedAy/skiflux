import re

from django.contrib.auth.password_validation import validate_password
from django.core import exceptions
from rest_framework import serializers

from skiflux.models import User
from skiflux.utils import (
    get_or_create_social_user,
    verify_apple_token,
    verify_facebook_token,
    verify_google_token,
)


class SignupSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=True, allow_blank=False)
    last_name = serializers.CharField(required=True, allow_blank=False)
    email = serializers.EmailField(required=True, allow_blank=False)
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate_password(self, value):
        user = User(
            first_name=self.initial_data.get("first_name", ""),
            last_name=self.initial_data.get("last_name", ""),
            email=self.initial_data.get("email", ""),
        )
        try:
            validate_password(value, user=user)
        except exceptions.ValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, attrs):
        if attrs.get("password") != attrs.get("password_confirm"):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs

    def validate_email(self, value):
        return value.lower()

    def validate_phone(self, value):
        if value:
            if User.objects.filter(phone=value).exists():
                raise serializers.ValidationError(
                    "A user with this phone number already exists."
                )
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        return value.lower()


class ForgotPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()


class ResetPasswordConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(write_only=True, min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs.get("new_password") != attrs.get("confirm_new_password"):
            raise serializers.ValidationError(
                {"confirm_new_password": "Passwords do not match."}
            )
        return attrs

    def validate_email(self, value):
        return value.lower()


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)

    def validate_email(self, value):
        return value.lower()


class RefreshTokenSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class VerifyForgotPasswordCode(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(write_only=True, min_length=6, max_length=6)

    def validate_email(self, value):
        return value.lower()


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()


class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class CompleteOnboardingSerializer(serializers.Serializer):
    username = serializers.CharField(required=True, allow_blank=False)
    skillworld = serializers.ListField(
        child=serializers.ChoiceField(choices=User.Skillworld.choices),
        allow_empty=False,
    )
    goal = serializers.ListField(
        child=serializers.ChoiceField(choices=User.Goal.choices),
        allow_empty=False,
    )
    avatar = serializers.ImageField(write_only=True, required=False)
    country = serializers.CharField(
        max_length=2,
        required=False,
        allow_blank=True,
        help_text="ISO 3166-1 alpha-2 e.g. US, GB, NG",
    )

    def validate_username(self, value: str) -> str:
        value = value.strip().lower()
        if not re.match(r"^[a-z0-9_]+$", value):
            raise serializers.ValidationError(
                "Username may only contain lowercase letters, numbers, and underscores."
            )
        if value.startswith("_") or value.endswith("_"):
            raise serializers.ValidationError(
                "Username cannot start or end with an underscore."
            )
        if value.startswith(r"0-9"):
            raise serializers.ValidationError("Username cannot start with a number.")
        return value

    def validate_avatar(self, value):
        if not value:
            return value
        max_size_mb = 2
        if value.size > (max_size_mb * 1024 * 1024):
            raise serializers.ValidationError(
                f"Image file too large. Maximum size is {max_size_mb}MB."
            )
        valid_mime_types = [
            "image/jpeg",
            "image/png",
            "image/jpg",
            "image/webp",
        ]
        if value.content_type not in valid_mime_types:
            raise serializers.ValidationError(
                "Unsupported file format. Please upload a JPEG, PNG, or WEBP image."
            )
        return value


class GoogleSocialAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField()

    def validate(self, attrs):
        try:
            user_data = verify_google_token(attrs["id_token"])
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        try:
            user = get_or_create_social_user("google", user_data)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        attrs["user"] = user
        return attrs


class FacebookSocialAuthSerializer(serializers.Serializer):
    access_token = serializers.CharField()

    def validate(self, attrs):
        try:
            user_data = verify_facebook_token(attrs["access_token"])
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        try:
            user = get_or_create_social_user("facebook", user_data)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        attrs["user"] = user
        return attrs


class AppleSocialAuthSerializer(serializers.Serializer):
    identity_token = serializers.CharField()
    first_name = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
    )
    last_name = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
    )

    def validate(self, attrs):
        try:
            user_data = verify_apple_token(
                attrs["identity_token"],
                first_name=attrs.get("first_name", ""),
                last_name=attrs.get("last_name", ""),
            )
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        try:
            user = get_or_create_social_user("apple", user_data)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, min_length=8, required=True)
    confirm_new_password = serializers.CharField(write_only=True, required=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        user = self.context["request"].user
        try:
            validate_password(value, user=user)
        except exceptions.ValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    @staticmethod
    def validate(attrs):
        if attrs.get("new_password") != attrs.get("confirm_new_password"):
            raise serializers.ValidationError(
                {"confirm_new_password": "Passwords do not match."}
            )
        if attrs.get("new_password") == attrs.get("current_password"):
            raise serializers.ValidationError(
                {
                    "new_password": "New password cannot be the same as the current password."  # noqa: E501
                }
            )
        return attrs


class AuthTokenUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    is_onboarded = serializers.BooleanField()
    username = serializers.CharField(allow_null=True, required=False)
    avatar_url = serializers.URLField(allow_null=True, required=False)


class AuthTokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
    user = AuthTokenUserSerializer(required=False)


class RefreshTokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()
