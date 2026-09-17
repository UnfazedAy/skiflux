import hashlib
import logging
import secrets
import string
import textwrap
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone as django_timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from skiflux.models import BlacklistedToken, User
from skiflux.tasks import send_app_email_task

logger = logging.getLogger(__name__)

_DUMMY_OTP_HASH = make_password("000000")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


def is_account_locked(user_or_admin) -> bool:
    if user_or_admin.locked_until and user_or_admin.locked_until > timezone.now():
        return True
    return False


def record_failed_login(user_or_admin):
    user_or_admin.failed_login_attempts += 1
    user_or_admin.last_failed_login = timezone.now()

    if user_or_admin.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user_or_admin.locked_until = timezone.now() + timedelta(
            minutes=LOCKOUT_DURATION_MINUTES
        )
        logger.warning(
            f"Account {user_or_admin.email} locked due to too many failed attempts."
        )

    user_or_admin.save(
        update_fields=["failed_login_attempts", "last_failed_login", "locked_until"]
    )


def reset_failed_login_attempts(user_or_admin):
    if user_or_admin.failed_login_attempts > 0 or user_or_admin.locked_until:
        user_or_admin.failed_login_attempts = 0
        user_or_admin.locked_until = None
        user_or_admin.save(update_fields=["failed_login_attempts", "locked_until"])


def _token_hash(token: str) -> str:
    """SHA-256 fingerprint of a JWT — safe to use as a Redis key."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(raw_password: str) -> str:
    return make_password(raw_password)


def send_password_reset_otp_email(user_email: str, otp: str) -> bool:
    subject = "Your SkiFlux Password Reset code"
    message = textwrap.dedent(f"""\
        Hello,

        We received a request to reset your SkiFlux password.
        Your 6-digit reset code is:

        {otp}
        
        This code will expire in 5 minutes. If you did not request this,
        you can safely ignore this email.

        Best,
        The SkiFlux Team
        """)
    send_app_email_task.apply_async(args=[subject, message, user_email])
    return True


send_reset_password_email = send_password_reset_otp_email


def generate_otp(length=6):
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _otp_attempts_key(prefix: str, email: str) -> str:
    return f"{prefix}_attempts_{email}"


def _check_otp_rate_limit(attempts_key: str, max_attempts: int = 5) -> bool:
    """Returns True if under limit. Increments attempt counter."""
    attempts = cache.get(attempts_key, 0)
    if attempts >= max_attempts:
        return False
    cache.set(attempts_key, attempts + 1, timeout=600)
    return True


def _reset_otp_attempts(attempts_key: str):
    cache.delete(attempts_key)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    return check_password(raw_password, hashed_password)


def create_access_token(user_id: str) -> str:
    exp = (
        datetime.now(
            timezone.utc,
        )
        + settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]
    )
    payload = {
        "user_id": str(user_id),
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(
        payload, settings.SIMPLE_JWT["USER_SECRET_KEY"], algorithm="HS256"
    )


def create_refresh_token(user_id: str) -> str:
    exp = (
        datetime.now(
            timezone.utc,
        )
        + settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
    )
    payload = {
        "user_id": str(user_id),
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(
        payload, settings.SIMPLE_JWT["USER_SECRET_KEY"], algorithm="HS256"
    )


def set_password_reset_otp(email: str, otp: str):
    hashed_otp = hash_password(otp)
    cache.set(f"reset_otp_{email}", hashed_otp, timeout=300)
    _reset_otp_attempts(_otp_attempts_key("reset_otp", email))


def consume_password_reset_otp(email: str, otp: str) -> bool:
    attempts_key = _otp_attempts_key("reset_otp", email)
    if not _check_otp_rate_limit(attempts_key):
        raise ValueError("Too many attempts. Please request a new reset code.")

    stored_otp = cache.get(f"reset_otp_{email}")
    if stored_otp is None:
        return False
    is_valid = check_password(otp, stored_otp)
    if is_valid:
        cache.delete(f"reset_otp_{email}")
        _reset_otp_attempts(attempts_key)
    return is_valid


def peek_password_reset_otp(email: str, otp: str) -> bool:
    attempts_key = _otp_attempts_key("reset_otp", email)
    if not _check_otp_rate_limit(attempts_key):
        raise ValueError("Too many attempts. Please request a new reset code.")
    stored_otp = cache.get(f"reset_otp_{email}")
    if stored_otp is None:
        return False
    return check_password(otp, stored_otp)


def decode_token(token: str, scope: str) -> dict:
    """Decode a JWT. Scope must be explicitly 'user' or 'admin'."""
    if scope not in ("user", "admin"):
        raise ValueError("scope must be either 'user' or 'admin'")
    secret = (
        settings.SIMPLE_JWT["ADMIN_SECRET_KEY"]
        if scope == "admin"
        else settings.SIMPLE_JWT["USER_SECRET_KEY"]
    )
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")


def set_email_verification_otp(email: str, otp: str):
    hashed_otp = hash_password(otp)
    cache.set(f"verify_email_otp_{email}", hashed_otp, timeout=300)
    _reset_otp_attempts(_otp_attempts_key("verify_email", email))


def verify_email_otp(email: str, otp: str) -> bool:
    attempts_key = _otp_attempts_key("verify_email", email)
    if not _check_otp_rate_limit(attempts_key):
        raise ValueError("Too many attempts. Please request a new code.")

    stored_otp = cache.get(f"verify_email_otp_{email}")
    if stored_otp is None:
        return False
    is_valid = check_password(otp, stored_otp)
    if is_valid:
        cache.delete(f"verify_email_otp_{email}")
        _reset_otp_attempts(attempts_key)
    return is_valid


def send_verification_email(user_email: str, otp: str) -> bool:
    subject = "Verify your SkiFlux account"
    message = textwrap.dedent(f"""\
        Hello,

        Welcome to SkiFlux!
        Please verify your email address to get started.
        Your 6-digit verification code is:

        {otp}
        
        This code will expire in 5 minutes.

        Best,
        The SkiFlux Team
        """)
    send_app_email_task.apply_async(args=[subject, message, user_email])
    return True


def refresh_access_token(refresh_token: str) -> dict:
    t_hash = _token_hash(refresh_token)
    if cache.get(f"blacklisted_{t_hash}"):
        raise ValueError("Token is blacklisted.")
    try:
        payload = decode_token(refresh_token, scope="user")
    except (ValueError, TypeError) as e:
        raise ValueError(str(e))

    if BlacklistedToken.objects.filter(token_hash=t_hash).exists():
        cache.set(f"blacklisted_{t_hash}", "true", timeout=300)
        raise ValueError("Token is blacklisted.")

    if payload.get("type") != "refresh":
        raise ValueError("Invalid token type.")
    blacklist_token(refresh_token, payload=payload, token_hash=t_hash)
    user_id = payload.get("user_id")
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
    }


def create_admin_access_token(admin_id: str) -> str:
    exp = datetime.now(timezone.utc) + settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]
    payload = {
        "admin_id": str(admin_id),
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "type": "access",
        "scope": "admin",
    }
    return jwt.encode(
        payload,
        settings.SIMPLE_JWT["ADMIN_SECRET_KEY"],
        algorithm="HS256",
    )


def create_admin_refresh_token(admin_id: str) -> str:
    exp = datetime.now(timezone.utc) + settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
    payload = {
        "admin_id": str(admin_id),
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
        "scope": "admin",
    }
    return jwt.encode(
        payload,
        settings.SIMPLE_JWT["ADMIN_SECRET_KEY"],
        algorithm="HS256",
    )


def refresh_admin_access_token(refresh_token: str) -> dict:
    if is_token_blacklisted(refresh_token):
        raise ValueError("Token is blacklisted.")
    try:
        payload = decode_token(refresh_token, scope="admin")
    except ValueError as e:
        raise ValueError(str(e))

    if payload.get("type") != "refresh":
        raise ValueError("Invalid token type.")
    if payload.get("scope") != "admin":
        raise ValueError("Invalid token scope for admin portal.")
    blacklist_token(refresh_token, payload=payload, scope="admin")
    admin_id = payload["admin_id"]
    return {
        "access_token": create_admin_access_token(admin_id),
        "refresh_token": create_admin_refresh_token(admin_id),
    }


def blacklist_token(
    token: str,
    payload: dict = None,
    token_hash: str = None,
    scope: str = "user",
):
    if not payload:
        try:
            payload = decode_token(token, scope)
        except ValueError:
            return

    if not token_hash:
        token_hash = _token_hash(token)

    exp = payload.get("exp")
    if exp:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        BlacklistedToken.objects.get_or_create(
            token_hash=token_hash,
            defaults={
                "expires_at": expires_at,
            },
        )
        now = datetime.now(timezone.utc).timestamp()
        timeout = int(exp - now)
        if timeout > 0:
            cache.set(
                f"blacklisted_{token_hash}",
                "true",
                timeout=timeout,
            )


def is_token_blacklisted(token: str) -> bool:
    token_hash = _token_hash(token)
    if cache.get(f"blacklisted_{token_hash}") is not None:
        return True
    return BlacklistedToken.objects.filter(token_hash=token_hash).exists()


def get_or_create_social_user(provider: str, user_data: dict):
    email = user_data.get("email")
    social_id = user_data["social_id"]
    with transaction.atomic():
        try:
            return User.objects.select_for_update().get(
                auth_provider=provider, social_id=social_id
            )
        except User.DoesNotExist:
            pass
        if email:
            try:
                user = User.objects.select_for_update().get(email=email)
                if user.auth_provider not in (provider, "email"):
                    raise ValueError(
                        f"This email is already linked to {user.auth_provider}. "
                        "Please log in with that."
                    )
                user.auth_provider = provider
                user.social_id = social_id
                user.is_verified = True
                if not user.avatar_url:
                    user.avatar_url = user_data.get("avatar_url")
                user.save(
                    update_fields=[
                        "auth_provider",
                        "social_id",
                        "is_verified",
                        "avatar_url",
                    ]
                )
                _grant_registration_bonus(user)
                return user
            except User.DoesNotExist:
                pass
        else:
            raise ValueError(
                "Could not retrieve your email from the provider. "
                "Please ensure your email is visible in your account settings."
            )
        try:
            user = User(
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
                email=email,
                auth_provider=provider,
                social_id=social_id,
                avatar_url=user_data.get("avatar_url"),
                is_verified=True,
            )
            user.set_unusable_password()
            user.save()
            _grant_registration_bonus(user)
            return user
        except IntegrityError:
            user = User.objects.get(email=email)
            _grant_registration_bonus(user)
            return user


def _grant_registration_bonus(user: User) -> None:
    from skiflux.services.registration_bonus_service import RegistrationBonusService

    RegistrationBonusService().grant_if_eligible(user)


class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header.split(" ", 1)[1]
        try:
            payload = decode_token(token, scope="user")
            if payload.get("type") != "access":
                raise AuthenticationFailed("Invalid token type.")
            if payload.get("scope") == "admin":
                raise AuthenticationFailed("Admin tokens are not valid here.")
            user_id = payload["user_id"]
            cache_key = f"auth_user_{user_id}"
            user = cache.get(cache_key)
            if user is None:
                user = User.objects.get(id=user_id)
            today = django_timezone.localdate()
            if user.last_active_date != today:
                user = User.objects.get(id=user_id)
                from skiflux.services.gamification_service import GamificationService

                GamificationService().process_daily_activity(user)
            cache.set(cache_key, user, timeout=60)
            if not user.is_active:
                raise AuthenticationFailed("Account is suspended.")
            return (user, token)
        except (ValueError, User.DoesNotExist):
            raise AuthenticationFailed("Invalid token.")


class AdminJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header.split(" ", 1)[1]
        try:
            payload = decode_token(token, scope="admin")
            if payload.get("type") != "access":
                raise AuthenticationFailed("Invalid token type.")
            if payload.get("scope") != "admin":
                raise AuthenticationFailed(
                    "Consumer tokens are not valid on admin endpoints."
                )
            admin_id = payload.get("admin_id")
            if not admin_id:
                raise AuthenticationFailed("Malformed admin token.")
            from skiflux.models import AdminUser

            admin = AdminUser.objects.prefetch_related("roles").get(id=admin_id)
            if not admin.is_active:
                raise AuthenticationFailed("Admin account is deactivated.")
            return (admin, token)

        except AuthenticationFailed:
            raise

        except Exception:
            raise AuthenticationFailed("Invalid admin token.")


class JWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "skiflux.utils.auth.JWTAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }


class AdminJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "skiflux.utils.auth.AdminJWTAuthentication"
    name = "adminBearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }


def get_private_avatar_url(public_id: str) -> str | None:
    if not public_id:
        return None

    if public_id.startswith("http"):
        return public_id

    import cloudinary.utils

    signed_url, options = cloudinary.utils.cloudinary_url(
        public_id,
        type="private",
        sign_url=True,
    )
    return signed_url


def set_creator_verification_otp(email: str, otp: str):
    hashed = make_password(otp)
    cache.set(f"creator_verify_otp_{email}", hashed, timeout=600)
    _reset_otp_attempts(_otp_attempts_key("creator_verify", email))


def verify_creator_email_otp(email: str, otp: str) -> bool:
    attempts_key = _otp_attempts_key("creator_verify", email)
    if not _check_otp_rate_limit(attempts_key):
        raise ValueError("Too many attempts. Please request a new code.")
    stored_hash = cache.get(f"creator_verify_otp_{email}")
    if stored_hash is None:
        return False
    is_valid = check_password(otp, stored_hash)
    if is_valid:
        cache.delete(f"creator_verify_otp_{email}")
        _reset_otp_attempts(attempts_key)
    return is_valid


def send_admin_invitation_email(
    email: str,
    full_name: str,
    temporary_password: str,
) -> bool:
    subject = "You're invited to SkiFlux Admin"

    message = textwrap.dedent(
        f"""\
        Hello {full_name},

        You have been invited as an admin on SkiFlux.

        Here are your temporary login credentials:

        Email: {email}
        Temporary Password: {temporary_password}

        For security reasons, you will be required to change your password
        after your first login.
        
        You can login here at https://skiflux-admin.vercel.app/

        If you were not expecting this invitation, please ignore this email.

        Best,
        The SkiFlux Team
        """
    )

    send_app_email_task.apply_async(args=[subject, message, email])

    return True
