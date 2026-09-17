from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from skiflux.models.activity import ActivityLog
from skiflux.repositories.user_repository import UserRepository
from skiflux.services.activity import ActivityService
from skiflux.services.gamification_service import GamificationService
from skiflux.services.registration_bonus_service import RegistrationBonusService
from skiflux.utils import (
    blacklist_token,
    consume_password_reset_otp,
    create_access_token,
    create_refresh_token,
    generate_otp,
    get_private_avatar_url,
    hash_password,
    peek_password_reset_otp,
    refresh_access_token,
    send_verification_email,
    set_email_verification_otp,
    set_password_reset_otp,
    verify_email_otp,
)
from skiflux.utils.auth import (
    send_reset_password_email,
)
from skiflux.utils.lockout import (
    is_account_locked,
    record_failed_login,
    reset_failed_login_attempts,
)
from skiflux.utils.media import upload_to_minio


class AuthService:
    def __init__(self):
        self.user_repo = UserRepository()
        self.registration_bonus_service = RegistrationBonusService()
        self.gamification_service = GamificationService()

    def signup(self, **validated_data):
        if not validated_data.get("phone"):
            validated_data["phone"] = None

        try:
            user = self.user_repo.create(**validated_data)
        except IntegrityError:
            raise ValidationError(
                "If this email is new, you'll receive a verification code."
            )

        otp = generate_otp()
        set_email_verification_otp(user.email, otp)
        send_verification_email(user.email, otp)

        return user

    def verify_email(self, email: str, otp: str):
        if not verify_email_otp(email, otp):
            raise ValidationError({"otp": "Invalid or expired OTP."})

        user = self.user_repo.get_by_email(email)
        if not user:
            raise ValidationError({"email": "User no longer exists."})

        if user.is_verified:
            raise ValidationError({"email": "Email is already verified."})

        self.user_repo.update(user, is_verified=True)
        user.refresh_from_db()
        self.registration_bonus_service.grant_if_eligible(user)
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.USER_VERIFIED,
            description=f"{user.email} verified their account.",
            subject=user,
            metadata={"user_id": str(user.id)},
        )
        return user

    def login(self, request, email: str, password: str):
        user = self.user_repo.get_by_email(email)

        # Lockout check first
        if user and is_account_locked(user.email):
            raise ValidationError(
                "Account temporarily locked due to too many failed attempts. "
                "Please try again later or contact support."
            )

        if not user or not user.check_password(password):
            if user:
                record_failed_login(user.email)
            else:
                # Timing attack prevention
                check_password(password, "pbkdf2_sha256$260000$dummy$hash")
            raise ValidationError("Invalid credentials.")

        # Success → reset lockout counter
        reset_failed_login_attempts(user.email)

        if not user.is_verified:
            raise ValidationError("Please verify your email address before logging in.")

        if not user.is_active:
            raise ValidationError(
                "Your account has been suspended. Please contact support."
            )

        update_last_login(None, user=user)
        self.gamification_service.process_daily_activity(user)

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
                "avatar_url": get_private_avatar_url(user.avatar_url),
            },
        }

    def forgot_password(self, email: str):
        user = self.user_repo.get_by_email(email)
        if user:
            otp = generate_otp()
            set_password_reset_otp(email, otp)
            send_reset_password_email(user.email, otp)

    def reset_password(self, email: str, otp: str, new_password: str):
        user = self.user_repo.get_by_email(email)
        if not user:
            raise ValidationError({"email": "User does not exist."})

        try:
            validate_password(new_password, user=user)
        except Exception as e:
            raise ValidationError({"new_password": list(e.messages)})

        # confirm that new password is not the same as previous password
        if user.check_password(new_password):
            raise ValidationError(
                {"new_password": "New password cannot be the same as the old password."}
            )

        if not consume_password_reset_otp(email, otp):
            raise ValidationError({"otp": "Invalid or expired OTP."})

        self.user_repo.update(user, password=hash_password(new_password))

    def token_refresh(self, refresh_token: str) -> dict:
        try:
            from skiflux.utils import decode_token

            payload = decode_token(refresh_token, scope="user")
            user_id = payload.get("user_id")
            tokens = refresh_access_token(refresh_token)
            user = self.user_repo.get_by_id(user_id)
            if user:
                self.gamification_service.process_daily_activity(user)
            return tokens
        except ValueError as e:
            raise ValueError(str(e))

    def verify_password_otp(self, email: str, otp: str):
        if not peek_password_reset_otp(email, otp):
            raise ValidationError("Invalid or expired OTP.")

    def resend_otp(self, email: str):
        user = self.user_repo.get_by_email(email)
        if user:
            if user.is_verified:
                raise ValidationError("Email is already verified.")
            otp = generate_otp()
            set_email_verification_otp(user.email, otp)
            send_verification_email(user.email, otp)

    def logout(self, refresh_token: str):
        try:
            blacklist_token(refresh_token)
        except ValueError as e:
            raise ValueError(str(e))

    def complete_onboarding(self, user_id: str, data: dict, avatar_file=None):
        data.pop("avatar", None)
        minio_key = None

        try:
            with transaction.atomic():
                try:
                    user = self.user_repo.get_for_update_by_pk(user_id)
                except Exception:
                    raise ValidationError("User not found.")

                if user.is_onboarded:
                    raise ValidationError("User has already been onboarded.")

                username = data.get("username")
                if username:
                    if username.startswith("@"):
                        username = username[1:]
                    username = username.lower().strip()

                    existing = self.user_repo.get_by_username(username)
                    if existing and existing.id != user.id:
                        raise ValidationError(
                            {"username": "This username is already taken."}
                        )
                    data["username"] = username

                data["is_onboarded"] = True
                try:
                    user = self.user_repo.update(user, **data)
                except IntegrityError:
                    raise ValidationError(
                        {"username": "This username is already taken."}
                    )

            if avatar_file:
                from skiflux.tasks.content import upload_media_from_minio_task

                minio_key = upload_to_minio(avatar_file, folder="skiflux_avatars")
                upload_media_from_minio_task.apply_async(
                    args=[
                        str(user.id),
                        minio_key,
                        "avatar_url",
                        "User",
                        "image",
                    ]
                )

        except Exception as e:
            if minio_key:
                try:
                    from skiflux.utils.media import delete_from_minio

                    delete_from_minio(minio_key)
                except Exception:
                    pass
            raise e

        from skiflux.utils.platform_task_tracker import trigger_platform_task

        trigger_platform_task(user, "complete_profile")

        return user

    def change_password(self, user, current_password: str, new_password: str):
        if not user.check_password(current_password):
            raise ValidationError(
                {"current_password": "Current password is incorrect."}
            )

        try:
            validate_password(new_password, user=user)
        except Exception as e:
            messages = getattr(e, "messages", [str(e)])
            raise ValidationError({"new_password": list(messages)})

        if user.check_password(new_password):
            raise ValidationError(
                {"new_password": "New password cannot be the same as the old password."}
            )

        self.user_repo.update(user, password=hash_password(new_password))
        return user
