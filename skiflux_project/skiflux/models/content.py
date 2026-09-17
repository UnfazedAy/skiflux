import uuid

from django.db import models

from .admin_user import AdminUser
from .user import User
from typing import Optional


class Season(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(
        AdminUser,
        on_delete=models.CASCADE,
        related_name="seasons",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    skillworld = models.CharField(
        max_length=50,
        choices=User.Skillworld.choices,
    )
    cover_image_public_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class Episode(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PROCESSING = "processing", "Processing"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"
        FAILED = (
            "failed",
            "Upload Failed",
        )
        REVIEW = "review", "Under Review"
        FLAGGED = "flagged", "Flagged Content"

    class AccessType(models.TextChoices):
        FREE = "free", "Free"
        PAID = "paid", "Paid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="episodes", default=None
    )
    creator = models.ForeignKey(
        AdminUser,
        on_delete=models.CASCADE,
        related_name="episodes",
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    order = models.PositiveSmallIntegerField(default=1, help_text="1-10")
    access_type = models.CharField(
        max_length=10, choices=AccessType.choices, default=AccessType.PAID
    )
    video_public_id = models.CharField(max_length=255, blank=True, null=True)
    thumbnail_public_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    video_duration = models.PositiveIntegerField(
        default=0,
        help_text="Video duration in seconds",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    view_count = models.PositiveIntegerField(default=0)
    liked_by = models.ManyToManyField(
        "skiflux.User", related_name="liked_episodes", blank=True
    )
    save_later = models.ManyToManyField(
        "skiflux.User", related_name="saved_episodes", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_episodes",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    submitted_for_review_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order"]
        unique_together = [("season", "order")]


class EpisodeResource(models.Model):
    class ResourceType(models.TextChoices):
        FILE = "file", "File"
        LINK = "link", "External Link"

    class FileType(models.TextChoices):
        PDF = "pdf", "PDF"
        FIGMA = "figma", "Figma"
        ZIP = "zip", "ZIP"
        IMAGE = "image", "Image"
        DOC = "doc", "Document"
        XLSX = "xlsx", "Excel"
        CSV = "csv", "CSV"
        OTHER = "other", "Other"

        @classmethod
        def from_mime_type(cls, mime_type: Optional[str]):
            if not mime_type:
                return cls.OTHER

            mapping = {
                # PDF
                "application/pdf": cls.PDF,
                # ZIP
                "application/zip": cls.ZIP,
                "application/x-zip-compressed": cls.ZIP,
                # Images
                "image/png": cls.IMAGE,
                "image/jpeg": cls.IMAGE,
                "image/jpg": cls.IMAGE,
                "image/gif": cls.IMAGE,
                "image/webp": cls.IMAGE,
                # Docs
                "text/plain": cls.DOC,
                "application/msword": cls.DOC,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": cls.DOC,  # noqa E501
                # Excel
                "application/vnd.ms-excel": cls.XLSX,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": cls.XLSX,  # noqa E501
            }

            return mapping.get(mime_type, cls.OTHER)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    episode = models.ForeignKey(
        "skiflux.Episode",
        on_delete=models.CASCADE,
        related_name="resources",
    )
    resource_type = models.CharField(
        max_length=10,
        choices=ResourceType.choices,
    )

    # ── file fields (resource_type = file) ──
    file_public_id = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Cloudinary public_id after upload completes.",
    )
    file_url = models.URLField(max_length=2000, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    file_size = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Size in bytes.",
    )
    file_type = models.CharField(
        max_length=20,
        choices=FileType.choices,
        blank=True,
        null=True,
    )
    content_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="MIME type e.g. application/pdf",
    )
    is_processing = models.BooleanField(
        default=False,
        help_text="True while the file is being uploaded to Cloudinary.",
    )

    # ── link fields (resource_type = link) ──
    link_label = models.CharField(max_length=255, blank=True, null=True)
    link_url = models.URLField(max_length=2000, blank=True, null=True)

    order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order within the episode.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["episode", "resource_type"]),
        ]

    def __str__(self):
        if self.resource_type == self.ResourceType.LINK:
            return f"Link: {self.link_label} → {self.link_url}"
        return f"File: {self.file_name}"

    @property
    def is_file(self) -> bool:
        return self.resource_type == self.ResourceType.FILE

    @property
    def is_link(self) -> bool:
        return self.resource_type == self.ResourceType.LINK


class EpisodePurchase(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "skiflux.User", on_delete=models.CASCADE, related_name="purchases"
    )
    episode = models.ForeignKey(
        Episode, on_delete=models.CASCADE, related_name="purchases"
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    purchased_at = models.DateTimeField(auto_now_add=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("user", "episode")]


class EpisodeView(models.Model):
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="viewed_episodes",
    )
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name="views",
    )
    viewed_at = models.DateTimeField(auto_now_add=True)
    watch_duration_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = [("user", "episode")]


class EpisodeNotInterested(models.Model):
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="not_interested_episodes",
    )
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name="not_interested_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "episode")]
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]


class EpisodeComment(models.Model):
    episode = models.ForeignKey(
        Episode, on_delete=models.CASCADE, related_name="comments"
    )
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="episode_comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )
    text = models.TextField(blank=True, default="")
    audio_public_id = models.CharField(max_length=255, blank=True, null=True)
    liked_by = models.ManyToManyField(
        User,
        related_name="liked_comments",
        blank=True,
    )
    liked_by_admins = models.ManyToManyField(
        AdminUser,
        related_name="liked_comments",
        blank=True,
    )
    flagged = models.BooleanField(default=False)
    flagged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class EpisodeTask(models.Model):
    class Kind(models.TextChoices):
        PROJECT_BASED = "project_based", "Project Based"
        ASSESSMENT = "assessment", "Assessment"

    class ProofType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        LINK = "link", "Link"
        FILE = "file", "File"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name="tasks",
    )

    kind = models.CharField(max_length=30, choices=Kind.choices)
    sla_time_limit_hours = models.PositiveSmallIntegerField(
        default=24,
        help_text="Creator-defined task SLA in hours. Defaults to 24 hours.",
    )

    task_brief = models.TextField(blank=True)
    accepted_proof_types = models.JSONField(
        default=list,
        help_text='Creator defined e.g. ["link", "image", "video", "file"]. '
        "Learners may submit a link, text notes, and/or an uploaded proof file.",
        blank=True,
    )

    pass_score_percent = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="e.g. 70 means 70% to pass",
    )
    time_limit_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="null means no time limit",
    )
    max_attempts = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="null means unlimited",
    )

    completion_criteria = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.kind}: {self.episode.title}"


class TaskSubmission(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        EpisodeTask, on_delete=models.CASCADE, related_name="submissions"
    )
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="task_submissions",
    )
    submission_text = models.TextField(blank=True)
    submission_url = models.URLField(blank=True, null=True)
    submission_file_public_id = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Cloudinary public_id for uploaded proof file.",
    )
    submission_file_url = models.URLField(max_length=2000, blank=True, null=True)
    submission_file_name = models.CharField(max_length=255, blank=True, null=True)
    submission_file_content_type = models.CharField(
        max_length=100, blank=True, null=True
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    cashback_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
    )
    rejection_reason = models.TextField(blank=True, null=True)
    reviewed_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_task_submissions",
    )
    feedback = models.TextField(blank=True, null=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("task", "user")]


class Follow(models.Model):
    follower = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="following",
    )
    creator = models.ForeignKey(
        AdminUser,
        on_delete=models.CASCADE,
        related_name="followers",
    )

    class NotificationMode(models.TextChoices):
        ALL = "all", "All updates"
        PERSONALIZED = "personalized", "Personalized"
        NONE = "none", "None"

    followed_at = models.DateTimeField(auto_now_add=True)
    notifications_enabled = models.BooleanField(
        default=True,
        help_text="Whether user wants notifications (bell) for "
        "new episodes from this creator.",
    )
    notification_mode = models.CharField(
        max_length=20,
        choices=NotificationMode.choices,
        default=NotificationMode.ALL,
        help_text="Per-creator notification mode for followed creators.",
    )

    class Meta:
        unique_together = [("follower", "creator")]
        ordering = ["-followed_at"]
        indexes = [
            models.Index(fields=["follower", "notifications_enabled"]),
        ]

    def __str__(self):
        return f"{self.follower} → {self.creator}"


class EpisodeRating(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name="ratings",
    )
    user = models.ForeignKey(
        "skiflux.User",
        on_delete=models.CASCADE,
        related_name="episode_ratings",
    )
    score = models.PositiveSmallIntegerField(
        help_text="Rating from 1 to 5.",
    )
    review = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("episode", "user")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score__gte=1) & models.Q(score__lte=5),
                name="rating_score_1_to_5",
            )
        ]

    def __str__(self):
        return f"{self.user} rated {self.episode} → {self.score}/5"


class AssessmentQuestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        EpisodeTask,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    order = models.PositiveSmallIntegerField(default=1)
    question_text = models.TextField()
    option_a = models.CharField(max_length=500)
    option_b = models.CharField(max_length=500)
    option_c = models.CharField(max_length=500)
    option_d = models.CharField(max_length=500)
    correct_answer = models.CharField(
        max_length=1,
        choices=[("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")],
    )

    class Meta:
        ordering = ["order"]
        unique_together = [("task", "order")]

    def __str__(self):
        return f"Q{self.order}: {self.question_text[:60]}"


class AssessmentSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        EpisodeTask, on_delete=models.CASCADE, related_name="assessment_submissions"
    )
    user = models.ForeignKey(
        "skiflux.User", on_delete=models.CASCADE, related_name="assessment_submissions"
    )
    cashback_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
    )
    attempt_number = models.PositiveSmallIntegerField(default=1)
    score_percent = models.PositiveSmallIntegerField()
    passed = models.BooleanField()
    answers = models.JSONField(
        default=dict,
        help_text='e.g. {"question_id": "A", ...}',
    )
    time_taken_seconds = models.PositiveIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("task", "user", "attempt_number")]
        ordering = ["-submitted_at"]
