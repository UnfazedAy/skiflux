import sys
from datetime import timedelta
from pathlib import Path

import cloudinary
import dj_database_url
import sentry_sdk
from decouple import config
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config(
    "SECRET_KEY", default="django-insecure-dummy-key-for-local-dev-and-testing-purposes"
)

DEBUG = config("DEBUG", default=False, cast=bool)

PAYLOAD_ENCRYPTION_KEY = config("PAYLOAD_ENCRYPTION_KEY", default="")

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default=config("ALLOWED_HOST", default="*"),
    cast=lambda v: [s.strip() for s in v.split(",")],
)

_cors_origins = config(
    "CORS_ALLOWED_ORIGINS",
    default="*",
    cast=lambda v: [s.strip() for s in v.split(",")],
)

if "*" in _cors_origins:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOWED_ORIGINS = []
else:
    CORS_ALLOWED_ORIGINS = _cors_origins

CORS_ALLOW_CREDENTIALS = True

AUTH_USER_MODEL = "skiflux.User"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "skiflux",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "skiflux_project.urls"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "skiflux.utils.exceptions.skiflux_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "skiflux.utils.auth.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "forgot_password": "500/hour",
        "otp_resend": "500/hour",
        "admin_login": "500/minute",
        "investor_submit": "50/hour",
    },
    "DEFAULT_PAGINATION_CLASS": "skiflux.utils.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SkiFlux API",
    "DESCRIPTION": (
        "Backend API documentation and testing for SkiFlux. "
        "Successful learner responses use envelope "
        "{status, status_code, message, data}; documented 200 schemas describe "
        "the `data` payload unless noted otherwise."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SECURITY": [{"bearerAuth": []}],
    "COMPONENTS": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
    "ENUM_NAME_OVERRIDES": {
        "AdminUserRoleTypeEnum": "skiflux.models.admin_user.AdminUser.RoleType",
        "AdminUserStatusEnum": "skiflux.models.admin_user.AdminUser.Status",
        "ActivityActionTypeEnum": "skiflux.models.activity.ActivityLog.ActionType",
        "UserBehaviourActionEnum": "skiflux.models.user_behaviour_log.UserBehaviourLog.Action",  # noqa: E501
        "SkillcoinTransactionTypeEnum": "skiflux.models.wallet.SkillcoinTransaction.Type",  # noqa: E501
        "SkillcoinTransactionStatusEnum": "skiflux.models.wallet.SkillcoinTransaction.Status",  # noqa: E501
        "UserGoalEnum": "skiflux.models.user.User.Goal",
        "UserSkillworldEnum": "skiflux.models.user.User.Skillworld",
        "EpisodeStatusEnum": "skiflux.models.content.Episode.Status",
        "EpisodeAccessTypeEnum": "skiflux.models.content.Episode.AccessType",
        "EpisodeTaskKindEnum": "skiflux.models.content.EpisodeTask.Kind",
        "WithdrawalRequestStatusEnum": "skiflux.models.wallet.WithdrawalRequest.Status",
        "PaymentTransactionStatusEnum": "skiflux.models.wallet.PaymentTransaction.Status",  # noqa: E501
        "WithdrawalAccountStatusEnum": "skiflux.models.wallet.WithdrawalAccount.Status",
        "WithdrawalHoldStatusEnum": "skiflux.models.wallet.WithdrawalHold.Status",
        # Resolve spectacular enum naming collisions/warnings seen in logs
        "ActionEnum": "skiflux.models.activity.ActivityLog.ActionType",
        "RoleTypeEnum": "skiflux.models.admin_user.AdminUser.RoleType",
        "RemoveRoleTypesEnum": "skiflux.models.admin_user.AdminUser.RoleType",
    },
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "skiflux_project.wsgi.application"

_is_testing = "test" in sys.argv or any("pytest" in arg for arg in sys.argv)

if _is_testing:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    DATABASES = {
        "default": {
            **dj_database_url.parse(
                config("DATABASE_URL"),
                conn_max_age=config("DB_CONN_MAX_AGE", default=60, cast=int),
                conn_health_checks=True,
            ),
            "TEST": {
                "NAME": config("TEST_DATABASE_NAME", default="test_skiflux"),
            },
        }
    }

    if config("DB_DISABLE_CURSORS", default=False, cast=bool):
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",  # noqa: E501
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "skiflux.utils.password_validation.ComplexPasswordValidator",
    },
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("ACCESS_TOKEN_LIFETIME_MINUTES", default=30, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("REFRESH_TOKEN_LIFETIME_DAYS", default=7, cast=int)
    ),
    "PASSWORD_RESET_TOKEN_LIFETIME": timedelta(
        minutes=config("PASSWORD_RESET_TOKEN_LIFETIME", default=10, cast=int)
    ),
    "USER_SECRET_KEY": config("USER_JWT_SECRET", default=config("SECRET_KEY")),
    "ADMIN_SECRET_KEY": config("ADMIN_JWT_SECRET", default=config("SECRET_KEY")),
}

SENTRY_DSN = config("SENTRY_DSN", default=None)

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
        ],
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        send_default_pii=True,
    )

MINIO_ENDPOINT_URL = config(
    "MINIO_ENDPOINT_URL",
    default="https://0c63dc67fa656b609ff05c36dd791866.r2.cloudflarestorage.com",
)
MINIO_ACCESS_KEY = config("MINIO_ACCESS_KEY", default="")
MINIO_SECRET_KEY = config("MINIO_SECRET_KEY", default="")
MINIO_BUCKET_NAME = config("MINIO_BUCKET_NAME", default="skiflux-uploads")

FIREBASE_SERVICE_ACCOUNT = config(
    "FIREBASE_SERVICE_ACCOUNT",
    default="",
)

FIREBASE_SERVICE_ACCOUNT_PATH = config(
    "FIREBASE_SERVICE_ACCOUNT_PATH",
    default="credentials/firebase-service-account.json",
)

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Africa/Lagos"

USE_I18N = True

USE_TZ = True

PHONENUMBER_DB_FORMAT = "E164"

REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Lagos"
CELERY_ALWAYS_EAGER = False
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# CELERY_WORKER_POOL = 'solo'

CELERY_BROKER_POOL_LIMIT = 1
CELERY_REDIS_MAX_CONNECTIONS = 50

if "test" in sys.argv or any("pytest" in arg for arg in sys.argv):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-snowflake",
        }
    }

    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    CLOUDINARY_EAGER_WEBHOOK_URL = ""
    CLOUDINARY_STREAMING_FALLBACK_DELAY_SECONDS = 0
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "max_connections": 50,
                "retry_on_timeout": True,
            },
        }
    }

DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL")
BREVO_API_KEY = config("BREVO_API_KEY")

FCM_SERVER_KEY = config("FCM_SERVER_KEY", default="")


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

GOOGLE_CLIENT_ID = config("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = config("GOOGLE_CLIENT_SECRET", default="")
GOOGLE_REDIRECT_URI = config(
    "GOOGLE_REDIRECT_URI", default="http://127.0.0.1:8000/auth/social/google/callback/"
)

FACEBOOK_APP_ID = config("FACEBOOK_APP_ID", default="")
FACEBOOK_APP_SECRET = config("FACEBOOK_APP_SECRET", default="")
FACEBOOK_REDIRECT_URI = config(
    "FACEBOOK_REDIRECT_URI",
    default="http://localhost:8000/auth/social/facebook/callback/",
)

APPLE_CLIENT_ID = config("APPLE_CLIENT_ID", default="")
APPLE_TEAM_ID = config("APPLE_TEAM_ID", default="")
APPLE_KEY_ID = config("APPLE_KEY_ID", default="")
APPLE_PRIVATE_KEY = config("APPLE_PRIVATE_KEY", default="").replace("\\n", "\n")
APPLE_REDIRECT_URI = config(
    "APPLE_REDIRECT_URI", default="http://127.0.0.1:8000/auth/social/apple/callback/"
)

SOCIAL_AUTH_SUCCESS_REDIRECT = config(
    "SOCIAL_AUTH_SUCCESS_REDIRECT", default="skiflux://auth"
)
SOCIAL_AUTH_FAILURE_REDIRECT = config(
    "SOCIAL_AUTH_FAILURE_REDIRECT", default="skiflux://auth/error"
)

PUBLIC_API_BASE_URL = config("PUBLIC_API_BASE_URL", default="http://127.0.0.1:8000")
CLOUDINARY_EAGER_WEBHOOK_URL = config(
    "CLOUDINARY_EAGER_WEBHOOK_URL",
    default=(f"{PUBLIC_API_BASE_URL.rstrip('/')}/api/v1/webhooks/cloudinary/eager/"),
)
CLOUDINARY_WEBHOOK_TOLERANCE_SECONDS = config(
    "CLOUDINARY_WEBHOOK_TOLERANCE_SECONDS",
    default=300,
    cast=int,
)
CLOUDINARY_STREAMING_FALLBACK_DELAY_SECONDS = config(
    "CLOUDINARY_STREAMING_FALLBACK_DELAY_SECONDS",
    default=600,
    cast=int,
)

cloudinary.config(
    cloud_name=config("CLOUDINARY_CLOUD_NAME"),
    api_key=config("CLOUDINARY_API_KEY"),
    api_secret=config("CLOUDINARY_API_SECRET"),
    secure=True,
)

FLUTTERWAVE_SECRET_KEY = config("FLUTTERWAVE_SECRET_KEY", default="")
FLUTTERWAVE_WEBHOOK_SECRET = config("FLUTTERWAVE_WEBHOOK_SECRET", default="")
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")
STRIPE_SECRET_KEY = config("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = config("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = config("STRIPE_WEBHOOK_SECRET", default="")
ADYEN_API_KEY = config("ADYEN_API_KEY", default="")
ADYEN_MERCHANT_ACCOUNT = config("ADYEN_MERCHANT_ACCOUNT", default="")
ADYEN_ENVIRONMENT = config("ADYEN_ENVIRONMENT", default="test")
ADYEN_WEBHOOK_SECRET = config("ADYEN_WEBHOOK_SECRET", default="")
PAYMENT_REDIRECT_URL = config(
    "PAYMENT_REDIRECT_URL", default="skiflux://payment/callback"
)
GEMINI_API_KEY = config("GEMINI_API_KEY", default="")
SUPPORT_EMAIL_HOST = config("SUPPORT_EMAIL_HOST", default="imap.gmail.com")
SUPPORT_EMAIL_PORT = config("SUPPORT_EMAIL_PORT", default=993, cast=int)
SUPPORT_EMAIL_USERNAME = config("SUPPORT_EMAIL_USERNAME", default="")
SUPPORT_EMAIL_PASSWORD = config("SUPPORT_EMAIL_PASSWORD", default="")
SUPPORT_SMTP_HOST = config("SUPPORT_SMTP_HOST", default="smtp.gmail.com")
SUPPORT_SMTP_PORT = config("SUPPORT_SMTP_PORT", default=465, cast=int)
