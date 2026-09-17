import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField


class UserManager(BaseUserManager):
    def create_user(self, email, first_name, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, first_name=first_name, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, first_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, first_name, password, **extra_fields)


class User(AbstractBaseUser):
    class Goal(models.TextChoices):
        BUILD_PORTFOLIO = "build_portfolio", "Build a verified portfolio"
        LEARN_SKILL = "learn_skill", "Learn a new technical skill"
        EARN_INCOME = "earn_income", "Earn income through tasks"
        NETWORK = "network", "Network with creators"

    class Skillworld(models.TextChoices):
        DESIGN = "design", "Design"
        CODE = "code", "Code"
        WRITING = "writing", "Writing"
        MARKETING = "marketing", "Marketing"
        ENGINEERING = "engineering", "Engineering"
        PRODUCT = "product", "Product"
        BUSINESS = "business", "Business"
        LIFESTYLE = "lifestyle", "Lifestyle"
        HEALTH = "health", "Health"
        ENTREPRENEUR = "entrepreneur", "Entrepreneur"
        CRYPTO = "crypto", "Crypto"
        AI = "ai", "AI"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DEACTIVATED = "deactivated", "Deactivated"

    class AuthProvider(models.TextChoices):
        EMAIL = "email", "Email"
        GOOGLE = "google", "Google"
        FACEBOOK = "facebook", "Facebook"
        APPLE = "apple", "Apple"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(unique=True)
    phone = PhoneNumberField(unique=True, null=True, blank=True)
    password = models.CharField(max_length=255, blank=True, default="")
    username = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
    )
    goal = models.JSONField(
        choices=Goal.choices,
        default=list,
        null=True,
        blank=True,
    )

    skillworld = models.JSONField(
        default=list,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    is_onboarded = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    registration_bonus_granted = models.BooleanField(
        default=False,
        help_text="True after the one-time registration Skillcoin bonus is credited.",
    )
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    auth_provider = models.CharField(
        max_length=20,
        choices=AuthProvider.choices,
        default=AuthProvider.EMAIL,
    )
    social_id = models.CharField(max_length=255, blank=True, null=True)
    avatar_url = models.CharField(max_length=500, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    country = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        help_text="ISO 3166-1 alpha-2 e.g. 'US', 'GB'",
    )
    failed_login_attempts = models.PositiveIntegerField(default=0)
    last_failed_login = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    xp = models.PositiveIntegerField(default=0)
    current_level = models.CharField(max_length=50, default="novice")
    streak_count = models.PositiveIntegerField(default=0)
    last_active_date = models.DateField(null=True, blank=True)
    best_streak_count = models.PositiveIntegerField(default=0)
    total_streak_xp_earned = models.PositiveIntegerField(default=0)
    biometrics_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Whether the user has enabled biometric authentication on their device."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        indexes = [
            models.Index(fields=["auth_provider", "social_id"], name="idx_user_social"),
        ]
        ordering = ["created_at"]

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def wallet_lookup_kwargs(self) -> dict:
        return {"user": self}

    def has_module_perms(self, app_label):
        return self.is_superuser

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class UserDevice(models.Model):
    """Stores mobile device tokens (e.g. FCM) for push notifications.
    Supports both regular users (learners) and admin users (creators/admins).
    """

    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        WEB = "web", "Web"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="devices",
        null=True,
        blank=True,
    )
    admin_user = models.ForeignKey(
        "skiflux.AdminUser",
        on_delete=models.CASCADE,
        related_name="devices",
        null=True,
        blank=True,
    )
    token = models.CharField(
        max_length=512,
        unique=True,
        help_text="FCM / push provider token",
    )
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        default=Platform.ANDROID,
    )
    device_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Optional client-generated device identifier for deduplication",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Set to false on logout or token invalidation",
    )
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_user_device"
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["admin_user", "is_active"]),
        ]
        ordering = ["-last_seen_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(user__isnull=False) & models.Q(admin_user__isnull=True))
                    | (models.Q(user__isnull=True) & models.Q(admin_user__isnull=False))
                ),
                name="userdevice_must_have_exactly_one_owner",
            ),
        ]

    def __str__(self):
        owner = (
            self.user.email
            if self.user_id
            else (self.admin_user.email if self.admin_user_id else "unknown")
        )
        return f"{owner} - {self.platform} ({self.token[:20]}...)"
