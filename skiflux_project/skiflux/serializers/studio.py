import mimetypes
import re
from decimal import Decimal

from django.contrib.auth.password_validation import validate_password
from django.core import exceptions as django_exceptions
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from skiflux.models import (
    AdminUser,
    AssessmentQuestion,
    Episode,
    EpisodeResource,
    EpisodeTask,
    Season,
    User,
)
from skiflux.models.platform_settings import SystemContentConfig
from skiflux.models.wallet import SystemFinancialConfig
from skiflux.repositories.content_repository import ContentRepository
from skiflux.services import ContentAccessService
from skiflux.utils.auth import get_private_avatar_url
from skiflux.utils.media import (
    get_hls_streaming_url,
    get_private_media_url,
    get_private_video_thumbnail_url,
    validate_uploaded_thumbnail,
    validate_uploaded_video,
    get_private_video_download_url,
)


class CreatorRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=50)
    last_name = serializers.CharField(max_length=50)
    username = serializers.CharField(max_length=20)

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
        if value and value[0].isdigit():
            raise serializers.ValidationError("Username cannot start with a number.")
        return value

    def validate_email(self, value: str) -> str:
        return value.lower().strip()

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except django_exceptions.ValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, attrs: dict):
        if attrs.get("password") != attrs.get("password_confirm"):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs


class AssessmentQuestionResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentQuestion
        fields = [
            "id",
            "question_text",
            "option_a",
            "option_b",
            "option_c",
            "option_d",
            "order",
            "correct_answer",
        ]


class AssessmentQuestionOwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentQuestion
        fields = [
            "id",
            "question_text",
            "option_a",
            "option_b",
            "option_c",
            "option_d",
            "order",
            "correct_answer",
        ]


class UserProjectSubmissionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    submission_url = serializers.URLField(allow_null=True)
    submission_text = serializers.CharField(allow_blank=True)
    cashback_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    rejection_reason = serializers.CharField(allow_null=True, allow_blank=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class UserAssessmentSubmissionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    score_percent = serializers.IntegerField()
    passed = serializers.BooleanField()
    answers = serializers.JSONField()
    cashback_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    attempt_number = serializers.IntegerField()
    time_taken_seconds = serializers.IntegerField(allow_null=True)
    submitted_at = serializers.DateTimeField()


class ProjectTaskResponseSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)

    class Meta:
        model = EpisodeTask
        fields = [
            "id",
            "status",
            "sla_time_limit_hours",
            "task_brief",
            "accepted_proof_types",
            "completion_criteria",
        ]
        read_only_fields = ["id"]


class AssessmentTaskResponseSerializer(serializers.ModelSerializer):
    questions = AssessmentQuestionResponseSerializer(many=True, read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = EpisodeTask
        fields = [
            "id",
            "status",
            "sla_time_limit_hours",
            "pass_score_percent",
            "time_limit_minutes",
            "max_attempts",
            "questions",
        ]
        read_only_fields = ["id"]


class EpisodeTasksResponseSerializer(serializers.Serializer):
    project_task = ProjectTaskResponseSerializer(required=False, allow_null=True)
    assessment_task = AssessmentTaskResponseSerializer(required=False, allow_null=True)
    my_project_submission = UserProjectSubmissionSerializer(
        required=False, allow_null=True
    )
    my_assessment_submissions = UserAssessmentSubmissionSerializer(
        many=True, required=False
    )


class EpisodeTaskSerializer(serializers.ModelSerializer):
    questions = AssessmentQuestionOwnerSerializer(many=True, read_only=True)

    class Meta:
        model = EpisodeTask
        fields = [
            "id",
            "kind",
            "sla_time_limit_hours",
            "task_brief",
            "accepted_proof_types",
            "pass_score_percent",
            "time_limit_minutes",
            "max_attempts",
            "completion_criteria",
            "questions",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        kind = attrs.get("kind")

        if kind == EpisodeTask.Kind.PROJECT_BASED:
            if not attrs.get("task_brief"):
                raise serializers.ValidationError(
                    {"task_brief": "Required for project-based tasks"}
                )

        elif kind == EpisodeTask.Kind.ASSESSMENT:
            if attrs.get("pass_score_percent") is None:
                raise serializers.ValidationError(
                    {"pass_score_percent": "Required for assessment tasks"}
                )

        else:
            raise serializers.ValidationError({"kind": "Invalid kind"})

        return attrs


class EpisodeResourceSerializer(serializers.ModelSerializer):
    is_file = serializers.ReadOnlyField()
    is_link = serializers.ReadOnlyField()

    class Meta:
        model = EpisodeResource
        fields = [
            "id",
            "resource_type",
            "is_file",
            "is_link",
            "file_url",
            "file_name",
            "file_size",
            "file_type",
            "link_label",
            "link_url",
            "order",
        ]


class CreatorSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    email = serializers.EmailField(source="creator.email", read_only=True)

    class Meta:
        model = AdminUser
        fields = [
            "id",
            "name",
            "username",
            "avatar_url",
            "followers_count",
            "email",
        ]

    def get_name(self, obj) -> str:
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_avatar_url(self, obj) -> str | None:
        if obj.avatar_public_id:
            return get_private_media_url(obj.avatar_public_id, resource_type="image")
        return None

    def get_followers_count(self, obj) -> int:
        return getattr(obj, "followers_count", obj.followers.count())


class EpisodeSerializer(serializers.ModelSerializer):
    tasks = EpisodeTaskSerializer(many=True, read_only=True)
    creator = CreatorSerializer(read_only=True)
    resources = EpisodeResourceSerializer(many=True, read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    season_id = serializers.UUIDField(source="season.id", read_only=True)
    season_title = serializers.CharField(source="season.title", read_only=True)
    skillworld = serializers.CharField(
        source="season.skillworld",
        read_only=True,
    )
    like_count = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    save_count = serializers.SerializerMethodField()
    skillcoin_price = serializers.SerializerMethodField()
    is_purchased = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()

    class Meta:
        model = Episode
        fields = [
            "id",
            "season_id",
            "season_title",
            "skillworld",
            "title",
            "description",
            "access_type",
            "skillcoin_price",
            "is_purchased",
            "is_locked",
            "thumbnail_url",
            "video_url",
            "preview_url",
            "download_url",
            "order",
            "status",
            "view_count",
            "like_count",
            "comment_count",
            "save_count",
            "created_at",
            "tasks",
            "resources",
            "creator",
            "video_duration",
        ]

    def get_like_count(self, obj) -> int:
        return getattr(obj, "like_count", obj.liked_by.count())

    def get_comment_count(self, obj) -> int:
        return getattr(obj, "comment_count", obj.comments.count())

    def get_save_count(self, obj) -> int:
        return getattr(obj, "save_count", obj.save_later.count())

    def _episode_is_purchased(self, obj) -> bool:
        if obj.access_type == Episode.AccessType.FREE:
            return False
        purchased_ids = self.context.get("purchased_episode_ids")
        if purchased_ids is not None:
            return obj.id in purchased_ids
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and getattr(user, "is_authenticated", False) and isinstance(user, User):
            return ContentRepository().has_purchased_episode(user, obj)
        return False

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_skillcoin_price(self, obj) -> str | None:
        if obj.access_type == Episode.AccessType.FREE:
            return None
        price = self.context.get("episode_purchase_price_skillcoins")
        if price is None:
            price = SystemFinancialConfig.get_config().episode_purchase_price_skillcoins
        return str(Decimal(str(price)).quantize(Decimal("0.01")))

    @extend_schema_field(serializers.BooleanField())
    def get_is_purchased(self, obj) -> bool:
        return self._episode_is_purchased(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_is_locked(self, obj) -> bool:
        if obj.access_type == Episode.AccessType.FREE:
            return False
        return not self._episode_is_purchased(obj)

    def get_thumbnail_url(self, obj) -> str | None:
        if obj.thumbnail_public_id:
            # Check if thumbnail is actually the video (auto-generated case)
            if obj.thumbnail_public_id == obj.video_public_id:
                return get_private_video_thumbnail_url(obj.thumbnail_public_id)
            else:
                # It's a real uploaded thumbnail image
                return get_private_media_url(
                    obj.thumbnail_public_id,
                    resource_type="image",
                )
        if obj.video_public_id:
            return get_private_video_thumbnail_url(obj.video_public_id)
        return None

    def get_video_url(self, obj) -> str | None:
        if not obj.video_public_id:
            return None

        request = self.context.get("request")
        if not request or not request.user:
            return None
        access_service = ContentAccessService()
        if access_service.can_user_access_episode(request.user, obj):
            return get_hls_streaming_url(obj.video_public_id)

        return None

    def get_preview_url(self, obj) -> str | None:
        if not obj.video_public_id:
            return None
        request = self.context.get("request")
        if not request or not request.user:
            return None

        return get_hls_streaming_url(obj.video_public_id, duration_seconds=30)

    def get_download_url(self, obj) -> str | None:
        if not obj.video_public_id:
            return None
        return get_private_video_download_url(obj.video_public_id)


class AssessmentQuestionSerializer(serializers.Serializer):
    question_text = serializers.CharField()
    option_a = serializers.CharField()
    option_b = serializers.CharField()
    option_c = serializers.CharField()
    option_d = serializers.CharField()
    correct_answer = serializers.ChoiceField(choices=["A", "B", "C", "D"])
    order = serializers.IntegerField(min_value=1)


class ProjectTaskInputSerializer(serializers.Serializer):
    sla_time_limit_hours = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    task_brief = serializers.CharField()
    accepted_proof_types = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        help_text="Creator-defined expected proof types e.g. ['link', 'image', "
        "'video', 'file'].",
    )
    completion_criteria = serializers.JSONField(required=False)


class AssessmentTaskInputSerializer(serializers.Serializer):
    sla_time_limit_hours = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    pass_score_percent = serializers.IntegerField(min_value=0, max_value=100)
    time_limit_minutes = serializers.IntegerField(min_value=1, required=False)
    max_attempts = serializers.IntegerField(min_value=1, required=False)
    questions = AssessmentQuestionSerializer(many=True, min_length=1)


class AttachTasksSerializer(serializers.Serializer):
    project_task = ProjectTaskInputSerializer(required=False)
    assessment_task = AssessmentTaskInputSerializer(required=False)

    def validate(self, attrs):
        if not attrs.get("project_task") and not attrs.get("assessment_task"):
            raise serializers.ValidationError(
                "At least one task type must be provided "
                "(project_task or assessment_task)."
            )
        return attrs


class UpdateTasksSerializer(AttachTasksSerializer):
    def validate(self, attrs):
        if "project_task" not in attrs and "assessment_task" not in attrs:
            raise serializers.ValidationError(
                "Provide project_task or assessment_task to update."
            )
        return attrs


class SeasonCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    skillworld = serializers.ChoiceField(choices=User.Skillworld.choices)
    cover_image_file = serializers.ImageField(required=False, allow_null=True)


class SeasonSerializer(serializers.ModelSerializer):
    episode_count = serializers.SerializerMethodField()

    class Meta:
        model = Season
        fields = [
            "id",
            "title",
            "description",
            "skillworld",
            "is_published",
            "price",
            "cover_image_public_id",
            "episode_count",
            "created_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_episode_count(self, obj) -> int:
        return obj.episodes.count()


class SeasonListCreatorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()


class SeasonListSerializer(serializers.ModelSerializer):
    cover_url = serializers.SerializerMethodField()
    creator = serializers.SerializerMethodField()
    episode_count = serializers.SerializerMethodField()

    class Meta:
        model = Season
        fields = [
            "id",
            "title",
            "description",
            "cover_url",
            "creator",
            "episode_count",
            "skillworld",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_cover_url(self, obj) -> str | None:
        if obj.cover_image_public_id:
            return get_private_media_url(
                obj.cover_image_public_id,
                resource_type="image",
            )
        return None

    @extend_schema_field(SeasonListCreatorSerializer())
    def get_creator(self, obj) -> dict:
        from skiflux.utils.media import creator_display_name

        creator = obj.creator
        return {
            "id": creator.id,
            "username": creator.username,
            "display_name": creator_display_name(creator),
        }

    @extend_schema_field(serializers.IntegerField())
    def get_episode_count(self, obj) -> int:
        if hasattr(obj, "episode_count"):
            return obj.episode_count
        return obj.episodes.filter(status=Episode.Status.PUBLISHED).count()


class SeasonWithStatsSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    description = serializers.CharField()
    skillworld = serializers.CharField()
    is_published = serializers.BooleanField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    cover_image_url = serializers.CharField(allow_null=True)
    episodes_count = serializers.IntegerField()
    submission_count = serializers.IntegerField()
    sla_avg = serializers.FloatField()
    created_at = serializers.DateTimeField()


class EpisodeCreateSerializer(serializers.Serializer):
    season_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    description = serializers.CharField()
    order = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    access_type = serializers.ChoiceField(
        choices=Episode.AccessType.choices, default=Episode.AccessType.PAID
    )
    video_file = serializers.FileField(required=True)
    thumbnail_file = serializers.ImageField(required=False, allow_null=True)

    ALLOWED_VIDEO_TYPES = [
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/x-msvideo",
    ]
    ALLOWED_THUMBNAIL_TYPES = [
        "image/jpeg",
        "image/png",
        "image/webp",
    ]
    MAX_THUMBNAIL_SIZE_MB = 5

    def validate_video_file(self, value):
        # Get actual max size from system config
        config = SystemContentConfig.get_config()
        max_video_size_mb = config.max_video_size_mb

        if value.size > max_video_size_mb * 1024 * 1024:
            raise serializers.ValidationError(
                f"Video file size cannot exceed {max_video_size_mb}MB."
            )
        if value.content_type not in self.ALLOWED_VIDEO_TYPES:
            raise serializers.ValidationError(
                f"Unsupported video format. Allowed: {', '.join(self.ALLOWED_VIDEO_TYPES)}"  # noqa: E501
            )
        return value

    def validate_thumbnail_file(self, value):
        return validate_uploaded_thumbnail(
            value, self.MAX_THUMBNAIL_SIZE_MB, self.ALLOWED_THUMBNAIL_TYPES
        )


class EpisodeReuploadSerializer(serializers.Serializer):
    video_file = serializers.FileField(required=True)
    thumbnail_file = serializers.ImageField(required=False, allow_null=True)

    ALLOWED_VIDEO_TYPES = EpisodeCreateSerializer.ALLOWED_VIDEO_TYPES
    ALLOWED_THUMBNAIL_TYPES = EpisodeCreateSerializer.ALLOWED_THUMBNAIL_TYPES
    MAX_THUMBNAIL_SIZE_MB = EpisodeCreateSerializer.MAX_THUMBNAIL_SIZE_MB

    def validate_video_file(self, value):
        # Get actual max size from system config
        config = SystemContentConfig.get_config()
        max_video_size_mb = config.max_video_size_mb
        return validate_uploaded_video(
            value, max_video_size_mb, self.ALLOWED_VIDEO_TYPES
        )

    def validate_thumbnail_file(self, value):
        return EpisodeCreateSerializer().validate_thumbnail_file(value)


class TrackViewSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField()
    watch_duration_seconds = serializers.IntegerField(min_value=0)
    completed = serializers.BooleanField(default=False)


class ProjectSubmissionInputSerializer(serializers.Serializer):
    submission_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text="Link to hosted work (Figma, GitHub, Google Doc, etc.).",
    )
    submission_text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional notes/description for your submission.",
    )
    submission_file = serializers.FileField(
        required=False,
        help_text="Optional uploaded proof file (image, PDF, video, etc.).",
    )

    BLOCKED_EXTENSIONS = {"exe", "msi", "bat", "cmd", "sh", "com", "scr"}

    def validate_submission_file(self, value):
        if not value:
            return value

        config = SystemContentConfig.get_config()
        max_bytes = config.max_submission_size_mb * 1024 * 1024
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f"File size cannot exceed {config.max_submission_size_mb}MB."
            )

        ext = value.name.rsplit(".", 1)[-1].lower() if "." in value.name else ""
        if ext in self.BLOCKED_EXTENSIONS:
            raise serializers.ValidationError(f"{ext} files are not allowed.")

        content_type = getattr(
            value,
            "content_type",
            mimetypes.guess_type(value.name)[0] or "application/octet-stream",
        )
        allowed_prefixes = ("image/", "video/", "application/", "text/")
        if not content_type.startswith(allowed_prefixes):
            raise serializers.ValidationError("Unsupported file type for submission.")

        return value

    def validate(self, attrs):
        url = attrs.get("submission_url")
        file = attrs.get("submission_file")
        if not url and not file:
            raise serializers.ValidationError(
                "Either submission_url or submission_file must be provided."
            )
        if url and file:
            raise serializers.ValidationError(
                "Provide either submission_url or submission_file, not both."
            )
        return attrs


class AssessmentSubmissionInputSerializer(serializers.Serializer):
    answers = serializers.DictField(
        child=serializers.ChoiceField(choices=["A", "B", "C", "D"]),
        help_text='Dictionary of question UUIDs mapped to answers, e.g. {"uuid": "A"}',
    )
    time_taken_seconds = serializers.IntegerField(min_value=0, required=False)


class ProjectSubmissionLinkSerializer(serializers.Serializer):
    """JSON-only project proof via link (no file upload)."""

    submission_url = serializers.URLField(
        help_text="Link to hosted work (Figma, GitHub, Google Doc, etc.).",
    )
    submission_text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional notes/description for your submission.",
    )


class SubmitTasksJsonSerializer(serializers.Serializer):
    """JSON body for project link and/or assessment submissions."""

    episode_id = serializers.UUIDField()
    project_submission = ProjectSubmissionLinkSerializer(
        required=False,
        help_text="Submit a project task using a hosted link.",
    )
    assessment_submission = AssessmentSubmissionInputSerializer(
        required=False,
        help_text="Submit assessment answers keyed by question UUID.",
    )


class SubmitTasksSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField()
    project_submission = ProjectSubmissionInputSerializer(required=False)
    assessment_submission = AssessmentSubmissionInputSerializer(required=False)
    # Flat multipart-friendly aliases for project submissions
    submission_url = serializers.URLField(required=False, allow_null=True)
    submission_text = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    submission_file = serializers.FileField(required=False)

    def validate(self, attrs):
        project_submission = attrs.get("project_submission")
        flat_fields = {
            key: attrs.pop(key, None)
            for key in ("submission_url", "submission_text", "submission_file")
        }
        flat_fields = {k: v for k, v in flat_fields.items() if v is not None}

        if flat_fields:
            if project_submission:
                raise serializers.ValidationError(
                    "Provide either nested project_submission or flat submission "
                    "fields, not both."
                )
            project_serializer = ProjectSubmissionInputSerializer(data=flat_fields)
            project_serializer.is_valid(raise_exception=True)
            attrs["project_submission"] = project_serializer.validated_data
        elif project_submission:
            attrs["project_submission"] = project_submission

        if not attrs.get("project_submission") and not attrs.get(
            "assessment_submission"
        ):
            raise serializers.ValidationError(
                "At least one submission type must be provided."
            )
        return attrs


class SubmitTasksMultipartSerializer(serializers.Serializer):
    """
    Flat multipart body for project file/link submissions (Swagger + form uploads).
    """

    episode_id = serializers.UUIDField()
    submission_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text="Link proof (Figma, GitHub, etc.). Use this OR submission_file.",
    )
    submission_text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional notes for your submission.",
    )
    submission_file = serializers.FileField(
        required=False,
        help_text=(
            "Upload proof file (image, PDF, video, etc.). Use this OR submission_url.",
        ),
    )


class EpisodePurchaseSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField()


class EpisodeActionSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField()


class EpisodeLikeResponseSerializer(serializers.Serializer):
    is_liked = serializers.BooleanField()


class EpisodeSaveResponseSerializer(serializers.Serializer):
    is_saved = serializers.BooleanField()


class EpisodePurchaseResponseSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField()


class CommentActionSerializer(serializers.Serializer):
    comment_id = serializers.IntegerField()


class EpisodeCommentReplySerializer(serializers.ModelSerializer):
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_last_name = serializers.CharField(source="user.last_name", read_only=True)
    user_avatar = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()

    class Meta:
        from skiflux.models.content import EpisodeComment

        model = EpisodeComment
        fields = [
            "id",
            "parent_id",
            "user_first_name",
            "user_last_name",
            "user_avatar",
            "text",
            "audio_public_id",
            "audio_url",
            "like_count",
            "is_liked",
            "created_at",
            "updated_at",
        ]

    def get_user_avatar(self, obj) -> str | None:
        return get_private_avatar_url(obj.user.avatar_url)

    def get_audio_url(self, obj) -> str | None:
        if obj.audio_public_id:
            return get_private_media_url(obj.audio_public_id, resource_type="video")
        return None

    def get_like_count(self, obj) -> int:
        return obj.liked_by.count()

    def get_is_liked(self, obj) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.liked_by.filter(id=request.user.id).exists()


class EpisodeCommentSerializer(serializers.ModelSerializer):
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_last_name = serializers.CharField(source="user.last_name", read_only=True)
    user_avatar = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        from skiflux.models.content import EpisodeComment

        model = EpisodeComment
        fields = [
            "id",
            "parent_id",
            "user_first_name",
            "user_last_name",
            "user_avatar",
            "text",
            "audio_public_id",
            "audio_url",
            "like_count",
            "is_liked",
            "replies",
            "created_at",
            "updated_at",
        ]

    def get_user_avatar(self, obj) -> str | None:
        return get_private_avatar_url(obj.user.avatar_url)

    def get_audio_url(self, obj) -> str | None:
        if obj.audio_public_id:
            return get_private_media_url(obj.audio_public_id, resource_type="video")
        return None

    def get_like_count(self, obj) -> int:
        return obj.liked_by.count()

    def get_is_liked(self, obj) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.liked_by.filter(id=request.user.id).exists()

    def get_replies(self, obj) -> list:
        replies = getattr(obj, "replies", None)
        if replies is None:
            return []
        return EpisodeCommentReplySerializer(
            replies.all(),
            many=True,
            context=self.context,
        ).data


class EpisodeCommentUpdateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500)


class EpisodeCommentReplyCreateSerializer(serializers.Serializer):
    text = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )
    audio_file = serializers.FileField(write_only=True, required=False)

    def validate(self, attrs):
        text = attrs.get("text")
        audio_file = attrs.get("audio_file")
        if not text and not audio_file:
            raise serializers.ValidationError(
                "Either text or audio_file must be provided."
            )
        return attrs


class EpisodeCommentCreateSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField()
    text = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )
    audio_file = serializers.FileField(write_only=True, required=False)

    def validate(self, attrs):
        text = attrs.get("text")
        audio_file = attrs.get("audio_file")
        if not text and not audio_file:
            raise serializers.ValidationError(
                "Either text or audio_file must be provided."
            )
        return attrs


class TaskSubmissionDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    user_id = serializers.UUIDField(source="user.id")
    user_email = serializers.EmailField(source="user.email")
    user_name = serializers.SerializerMethodField()
    user_avatar_url = serializers.CharField(source="user.avatar_url", allow_null=True)
    task_id = serializers.UUIDField(source="task.id")
    episode_id = serializers.UUIDField(source="task.episode.id")
    episode_title = serializers.CharField(source="task.episode.title")
    season_id = serializers.UUIDField(source="task.episode.season.id")
    season_title = serializers.CharField(source="task.episode.season.title")
    submission_text = serializers.CharField(allow_blank=True, allow_null=True)
    submission_url = serializers.URLField(allow_null=True, required=False)
    submission_file_url = serializers.SerializerMethodField()
    proof_type = serializers.SerializerMethodField()
    status = serializers.CharField()
    cashback_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)
    feedback = serializers.CharField(allow_blank=True, allow_null=True)
    reviewed_by = serializers.SerializerMethodField()
    reviewed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()

    def get_user_name(self, obj) -> str:
        return f"{obj.user.first_name} {obj.user.last_name}".strip()

    def get_submission_file_url(self, obj) -> str | None:
        from skiflux.utils.media import get_submission_file_url

        return get_submission_file_url(obj)

    def get_proof_type(self, obj) -> str | None:
        from skiflux.utils.media import derive_submission_proof_type

        return derive_submission_proof_type(obj)

    def get_reviewed_by(self, obj) -> str | None:
        if not obj.reviewed_by:
            return None
        return f"{obj.reviewed_by.first_name} {obj.reviewed_by.last_name}".strip()


class AssessmentSubmissionDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    user_id = serializers.UUIDField(source="user.id")
    user_email = serializers.EmailField(source="user.email")
    score_percent = serializers.FloatField()
    passed = serializers.BooleanField()
    answers = serializers.JSONField()
    attempt_number = serializers.IntegerField()
    cashback_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    time_taken_seconds = serializers.IntegerField(allow_null=True)
    submitted_at = serializers.DateTimeField()


class CreatorResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()


class StudioEpisodeSerializer(serializers.ModelSerializer):
    submission_count = serializers.SerializerMethodField()
    pending_submission_review_count = serializers.IntegerField(
        source="pending_submissions"
    )
    view_count = serializers.IntegerField(source="total_views")

    class Meta:
        model = Episode
        fields = [
            "id",
            "title",
            "status",
            "view_count",
            "created_at",
            "video_duration",
            "submission_count",
            "pending_submission_review_count",
        ]

    def get_submission_count(self, obj):
        return (obj.project_submissions or 0) + (obj.assessment_submissions or 0)


class SeasonStudioStatsSerializer(serializers.Serializer):
    """Header-level stats for the season studio view."""

    total_episodes = serializers.IntegerField()
    total_views = serializers.IntegerField()
    total_submissions = serializers.IntegerField()
    pending_review = serializers.IntegerField()


class EpisodeTaskDetailSerializer(serializers.Serializer):
    """Task details with submission counts."""

    id = serializers.UUIDField()
    episode_id = serializers.UUIDField()
    kind = serializers.CharField()
    status = serializers.CharField(default="active")
    sla_time_limit_hours = serializers.IntegerField()
    task_brief = serializers.CharField(allow_blank=True)
    accepted_proof_types = serializers.ListField()
    pass_score_percent = serializers.IntegerField(allow_null=True)
    time_limit_minutes = serializers.IntegerField(allow_null=True)
    max_attempts = serializers.IntegerField(allow_null=True)
    completion_criteria = serializers.JSONField()
    total_submissions = serializers.IntegerField()
    pending_submissions = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    questions = serializers.ListField(
        child=serializers.DictField(), required=False, allow_null=True
    )


class TaskSubmissionListItemSerializer(serializers.Serializer):
    """Single task submission in list."""

    id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    user_email = serializers.EmailField()
    user_name = serializers.CharField()
    user_avatar_url = serializers.CharField(allow_null=True)
    submission_text = serializers.CharField(allow_blank=True)
    submission_url = serializers.URLField(allow_null=True)
    submission_file_url = serializers.CharField(allow_null=True)
    proof_type = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    sla = serializers.CharField(allow_null=True)
    reviewed_by = serializers.CharField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    cashback_amount = serializers.CharField()
    rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)
    feedback = serializers.CharField(allow_blank=True, allow_null=True)


class SeasonTaskListItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    episode_id = serializers.UUIDField()
    episode_title = serializers.CharField()
    episode_order = serializers.IntegerField()
    kind = serializers.CharField()
    status = serializers.CharField(default="active")
    sla_time_limit_hours = serializers.IntegerField()
    task_brief = serializers.CharField(allow_blank=True)
    accepted_proof_types = serializers.ListField()
    pass_score_percent = serializers.IntegerField(allow_null=True)
    time_limit_minutes = serializers.IntegerField(allow_null=True)
    max_attempts = serializers.IntegerField(allow_null=True)
    completion_criteria = serializers.JSONField()
    total_submissions = serializers.IntegerField()
    pending_submissions = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class SeasonTaskListSerializer(serializers.Serializer):
    total_count = serializers.IntegerField()
    offset = serializers.IntegerField()
    limit = serializers.IntegerField()
    results = SeasonTaskListItemSerializer(many=True)


class TaskSubmissionListSerializer(serializers.Serializer):
    """Paginated task submissions."""

    total_count = serializers.IntegerField()
    offset = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False)
    results = TaskSubmissionListItemSerializer(many=True)


class WatchedEpisodeTaskItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    episode_id = serializers.UUIDField()
    episode_title = serializers.CharField()
    season_id = serializers.UUIDField()
    season_title = serializers.CharField()
    kind = serializers.CharField()
    status = serializers.CharField()
    sla_time_limit_hours = serializers.IntegerField()
    sla_deadline = serializers.DateTimeField(allow_null=True)
    task_brief = serializers.CharField(allow_blank=True)
    accepted_proof_types = serializers.ListField()
    pass_score_percent = serializers.IntegerField(allow_null=True)
    questions = AssessmentQuestionResponseSerializer(
        many=True,
        read_only=True,
    )
    time_limit_minutes = serializers.IntegerField(allow_null=True)
    max_attempts = serializers.IntegerField(allow_null=True)
    completion_criteria = serializers.JSONField()
    viewed_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)


class WatchedEpisodeTaskListSerializer(serializers.Serializer):
    total_count = serializers.IntegerField()
    offset = serializers.IntegerField()
    limit = serializers.IntegerField()
    results = WatchedEpisodeTaskItemSerializer(many=True)


class EpisodeCommentListItemSerializer(serializers.Serializer):
    """Single comment in list."""

    id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    user_email = serializers.EmailField()
    user_name = serializers.CharField()
    user_avatar_url = serializers.CharField(allow_null=True)
    episode_id = serializers.UUIDField(required=False)
    episode_title = serializers.CharField(required=False)
    text = serializers.CharField(allow_blank=True, default="")
    audio_public_id = serializers.CharField(allow_null=True, required=False)
    audio_url = serializers.URLField(allow_null=True, required=False)
    flagged = serializers.BooleanField(required=False)
    created_at = serializers.DateTimeField()


class EpisodeCommentListSerializer(serializers.Serializer):
    """Paginated comments."""

    total_count = serializers.IntegerField()
    offset = serializers.IntegerField()
    limit = serializers.IntegerField()
    results = EpisodeCommentListItemSerializer(many=True)


class SeasonUpdateSerializer(serializers.Serializer):
    """Serializer for updating a season."""

    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    skillworld = serializers.ChoiceField(
        choices=User.Skillworld.choices, required=False
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    cover_image_file = serializers.ImageField(required=False, allow_null=True)

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("Provide at least one field to update.")
        return attrs


class EpisodeUpdateSerializer(serializers.Serializer):
    """Serializer for updating an episode."""

    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False)
    order = serializers.IntegerField(min_value=1, max_value=10, required=False)
    access_type = serializers.ChoiceField(
        choices=Episode.AccessType.choices, required=False
    )
    thumbnail_file = serializers.ImageField(required=False, allow_null=True)

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("Provide at least one field to update.")
        return attrs


class PublishSeasonSerializer(serializers.Serializer):
    """Serializer for publishing/unpublishing a season."""

    pass


class PublishEpisodeSerializer(serializers.Serializer):
    """Serializer for publishing/unpublishing an episode."""

    pass
