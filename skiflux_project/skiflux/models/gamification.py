import uuid

from django.db import models


class Badge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField()
    icon_public_id = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_badge"
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserBadge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="user_badges",
    )
    badge = models.ForeignKey(
        Badge,
        on_delete=models.CASCADE,
        related_name="earned_by",
    )
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skiflux_user_badge"
        unique_together = ("user", "badge")
        ordering = ["-earned_at"]

    def __str__(self):
        return f"{self.user.email} - {self.badge.name}"


class PlatformTask(models.Model):
    class Category(models.TextChoices):
        ONBOARDING = "onboarding", "Onboarding"
        SOCIAL = "social", "Social"
        REFERRAL = "referral", "Referral"
        FLASH = "flash", "Flash Challenge"
        CREATOR_EVENT = "creator_event", "Creator Event"
        CUSTOM = "custom", "Custom"

    class TriggerType(models.TextChoices):
        NONE = "", "Manual (No Auto Tracking)"
        COMPLETE_PROFILE = "complete_profile", "Complete Profile"
        REFER_FRIEND = "refer_friend", "Refer a Friend"
        LINK_SOCIAL = "link_social", "Link Social Account"
        FIRST_DEPOSIT = "first_deposit", "First Deposit"
        FOLLOW_CREATOR = "follow_creator", "Follow Creator(s)"

    class VerificationMode(models.TextChoices):
        AUTOMATIC = "automatic", "Automatic"
        MANUAL = "manual", "Manual Submit + Claim"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=100, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.CUSTOM,
    )
    trigger_type = models.CharField(
        max_length=50,
        choices=TriggerType.choices,
        blank=True,
        default="",
        db_column="action_type",
    )
    verification_mode = models.CharField(
        max_length=20,
        choices=VerificationMode.choices,
        default=VerificationMode.AUTOMATIC,
    )
    progress_target = models.PositiveIntegerField(default=1)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    external_url = models.URLField(blank=True, default="")
    icon = models.CharField(max_length=100, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    xp_reward = models.PositiveIntegerField(default=0)
    skillcoin_reward = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skiflux_platform_task"
        ordering = ["sort_order", "title"]
        indexes = [
            models.Index(fields=["is_active", "sort_order"]),
            models.Index(fields=["trigger_type", "is_active"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_manual(self) -> bool:
        return not self.trigger_type

    @property
    def action_type(self) -> str:
        """Backward-compatible alias used in older code/tests."""
        return self.trigger_type


class UserPlatformTask(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        IN_PROGRESS = "in_progress", "In Progress"
        CLAIMABLE = "claimable", "Claimable"
        CLAIMED = "claimed", "Claimed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="platform_tasks_completed",
    )
    platform_task = models.ForeignKey(
        PlatformTask,
        on_delete=models.CASCADE,
        related_name="completed_by",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )
    progress_current = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    claimable_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "skiflux_user_platform_task"
        unique_together = ("user", "platform_task")
        ordering = ["-claimed_at", "-claimable_at", "-started_at"]

    def __str__(self):
        return f"{self.user.email} - {self.platform_task.title} ({self.status})"

    @property
    def completed(self) -> bool:
        return self.status == self.Status.CLAIMED

    @property
    def completed_at(self):
        return self.claimed_at
