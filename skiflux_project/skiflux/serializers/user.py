from rest_framework import serializers

from skiflux.serializers.studio import EpisodeSerializer
from skiflux.models.user import User
from skiflux.models.notification_preference import UserNotificationPreferences
import re


class UserManagementListSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    avatar_url = serializers.URLField(read_only=True, allow_null=True)

    created_at = serializers.DateTimeField(read_only=True)
    joined_at = serializers.DateTimeField(source="created_at", read_only=True)

    skillworld = serializers.JSONField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)

    tasks_done = serializers.IntegerField(read_only=True)
    coins = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    rank = serializers.IntegerField(read_only=True)
    xp = serializers.IntegerField(read_only=True)
    current_level = serializers.CharField(read_only=True)


class UserManagementStatsSerializer(serializers.Serializer):
    """
    Serializer for user management dashboard statistics.
    """

    total_users = serializers.IntegerField(help_text="Total number of learner users")
    active_users = serializers.IntegerField(help_text="Active users")
    suspended_users = serializers.IntegerField(help_text="Suspended users")
    deactivated_users = serializers.IntegerField(help_text="Deactivated users")
    new_this_week = serializers.IntegerField(help_text="New users who joined this week")


class WatchHistoryItemSerializer(serializers.Serializer):
    episode = EpisodeSerializer(read_only=True)
    watch_duration_seconds = serializers.IntegerField()
    completed = serializers.BooleanField()
    viewed_at = serializers.DateTimeField()


class ProfileEpisodeCardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    season_title = serializers.CharField(source="season.title")
    skillworld = serializers.CharField(source="season.skillworld")
    access_type = serializers.CharField()
    duration_seconds = serializers.IntegerField(source="video_duration")
    creator_name = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    def get_creator_name(self, obj) -> str:
        c = obj.creator
        return f"{c.first_name} {c.last_name}".strip() or c.email

    def get_thumbnail_url(self, obj) -> str | None:
        from skiflux.utils.media import (
            get_private_media_url,
            get_private_video_thumbnail_url,
        )

        if obj.thumbnail_public_id:
            # Check if thumbnail is actually the video (auto-generated case)
            if obj.thumbnail_public_id == obj.video_public_id:
                return get_private_video_thumbnail_url(obj.thumbnail_public_id)
            else:
                # It's a real uploaded thumbnail image
                return get_private_media_url(
                    obj.thumbnail_public_id, resource_type="image"
                )
        if obj.video_public_id:
            return get_private_video_thumbnail_url(obj.video_public_id)
        return None


class UserProfileSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    bio = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    goal = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    skillworld = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    bonus_balance = serializers.SerializerMethodField()
    xp = serializers.SerializerMethodField()
    current_level = serializers.SerializerMethodField()
    streak_count = serializers.SerializerMethodField()
    is_onboarded = serializers.BooleanField(source="user.is_onboarded")
    rank = serializers.IntegerField(allow_null=True)
    earned_badges = serializers.SerializerMethodField()
    task_done = serializers.SerializerMethodField()
    episode_completed = serializers.SerializerMethodField()
    biometrics_enabled = serializers.BooleanField(source="user.biometrics_enabled")

    watch_history_preview = WatchHistoryItemSerializer(many=True)

    def get_id(self, obj) -> str:
        return str(obj["user"].id)

    def get_first_name(self, obj) -> str:
        return obj["user"].first_name

    def get_last_name(self, obj) -> str:
        return obj["user"].last_name

    def get_email(self, obj) -> str:
        return obj["user"].email

    def get_username(self, obj):
        return obj["user"].username

    def get_skillworld(self, obj):
        return obj["user"].skillworld

    def get_status(self, obj) -> str:
        return obj["user"].status

    def get_balance(self, obj) -> str:
        return str(obj["wallet"].balance)

    def get_bonus_balance(self, obj) -> str:
        return str(obj["wallet"].bonus_balance)

    def get_bio(self, obj):
        return obj["user"].bio

    def get_phone(self, obj):
        return str(obj["user"].phone) if obj["user"].phone else None

    def get_country(self, obj):
        return obj["user"].country

    def get_goal(self, obj):
        return obj["user"].goal

    def get_avatar_url(self, obj):
        from skiflux.utils.auth import get_private_avatar_url

        return get_private_avatar_url(obj["user"].avatar_url)

    def get_xp(self, obj) -> int:
        return obj["user"].xp

    def get_current_level(self, obj) -> str:
        return obj["user"].current_level

    def get_streak_count(self, obj) -> int:
        return obj["user"].streak_count

    def get_earned_badges(self, obj):
        from skiflux.serializers.gamification import UserBadgeSerializer

        badges = obj["user"].user_badges.all()
        return UserBadgeSerializer(badges, many=True).data

    def get_task_done(self, obj):
        return obj["tasks_done"]

    def get_episode_completed(self, obj):
        return obj["episodes_completed"]


class PublicUserProfileSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    bio = serializers.SerializerMethodField()
    xp = serializers.SerializerMethodField()
    rank = serializers.IntegerField(allow_null=True)
    current_level = serializers.SerializerMethodField()
    task_done = serializers.SerializerMethodField()
    episode_completed = serializers.SerializerMethodField()
    skillworld = serializers.SerializerMethodField()
    earned_badges = serializers.SerializerMethodField()

    def get_id(self, obj) -> str:
        return str(obj["user"].id)

    def get_first_name(self, obj) -> str:
        return obj["user"].first_name

    def get_last_name(self, obj) -> str:
        return obj["user"].last_name

    def get_username(self, obj):
        return obj["user"].username

    def get_bio(self, obj):
        return obj["user"].bio

    def get_xp(self, obj) -> int:
        return obj["user"].xp

    def get_current_level(self, obj) -> str:
        return obj["user"].current_level

    def get_skillworld(self, obj):
        return obj["user"].skillworld

    def get_avatar_url(self, obj):
        from skiflux.utils.auth import get_private_avatar_url

        return get_private_avatar_url(obj["user"].avatar_url)

    def get_task_done(self, obj):
        return obj["tasks_done"]

    def get_episode_completed(self, obj):
        return obj["episode_completed"]

    def get_earned_badges(self, obj):
        from skiflux.serializers.gamification import UserBadgeSerializer

        badges = obj["user"].user_badges.select_related("badge").all()
        return UserBadgeSerializer(badges, many=True).data


class UpdateProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=255, required=False)
    last_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    username = serializers.CharField(
        max_length=50,
        required=False,
    )
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    country = serializers.CharField(
        max_length=2,
        required=False,
    )
    goal = serializers.ListField(
        child=serializers.ChoiceField(choices=User.Goal.values),
        required=False,
        allow_empty=True,
    )
    skillworld = serializers.ListField(
        child=serializers.ChoiceField(choices=User.Skillworld.values),
        required=False,
        allow_empty=True,
    )
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    avatar = serializers.ImageField(required=False, allow_null=True)

    def validate_username(self, value: str) -> str:
        if not value:
            return
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

    def validate_country(self, value):
        if value and len(value) != 2:
            raise serializers.ValidationError(
                "Country must be a 2-letter ISO code e.g. NG, US."
            )
        return value.upper() if value else value

    def validate(self, data):
        return data


class UserSubmissionSerializer(serializers.Serializer):
    """Unified serializer for user's project or assessment submissions in list."""

    id = serializers.UUIDField()
    type = serializers.CharField()  # "project" or "assessment"
    episode_id = serializers.UUIDField()
    episode_title = serializers.CharField()
    season_title = serializers.CharField()
    skillworld = serializers.CharField()
    task_id = serializers.UUIDField()
    status = serializers.CharField()
    submission_text = serializers.CharField(allow_blank=True, allow_null=True)
    submission_url = serializers.URLField(allow_null=True)
    submission_file_url = serializers.URLField(allow_null=True)
    proof_type = serializers.CharField(allow_null=True)
    cashback_amount = serializers.CharField(allow_null=True)
    rejection_reason = serializers.CharField(allow_blank=True, allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    score_percent = serializers.IntegerField(allow_null=True)
    passed = serializers.BooleanField(allow_null=True)
    answers = serializers.JSONField(allow_null=True)
    attempt_number = serializers.IntegerField(allow_null=True)
    time_taken_seconds = serializers.IntegerField(allow_null=True)
    submitted_at = serializers.DateTimeField(allow_null=True)


class DeviceRegisterSerializer(serializers.Serializer):
    """Serializer for registering a mobile device token for push notifications."""

    token = serializers.CharField(
        max_length=512,
        required=True,
        help_text="FCM token or equivalent push token from the mobile app",
    )
    platform = serializers.ChoiceField(
        choices=[
            ("ios", "iOS"),
            ("android", "Android"),
            ("web", "Web"),
        ],
        default="android",
        required=False,
    )
    device_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional unique device identifier from the client "
        "(for deduping tokens)",
    )


class UserLeaderboardEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    username = serializers.CharField(allow_null=True)
    avatar_url = serializers.SerializerMethodField()
    current_level = serializers.CharField()
    xp = serializers.IntegerField()
    rank = serializers.IntegerField()
    tasks_done = serializers.IntegerField()
    coins = serializers.DecimalField(max_digits=12, decimal_places=2)
    is_me = serializers.SerializerMethodField()

    def get_avatar_url(self, obj) -> str | None:
        if not obj.avatar_url:
            return None
        from skiflux.utils import get_private_avatar_url

        return get_private_avatar_url(obj.avatar_url)

    def get_is_me(self, obj) -> bool:
        request = self.context.get("request")
        if not request or not request.user:
            return False
        return str(obj.id) == str(request.user.id)


class BiometricsStatusSerializer(serializers.Serializer):
    biometrics_enabled = serializers.BooleanField()


class AppPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        from skiflux.models.app_preference import UserAppPreferences

        model = UserAppPreferences
        fields = [
            "auto_play_next",
            "download_quality",
            "download_on_wifi_only",
            "app_language",
            "save_watch_history",
            "personalised_recommendations",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class CreatorNotificationPreferenceUpdateSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=["all", "personalized", "none"],
    )


class CreatorNotificationPreferenceSerializer(serializers.Serializer):
    creator_id = serializers.UUIDField()
    mode = serializers.ChoiceField(
        choices=["all", "personalized", "none"],
    )


class NotificationPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotificationPreferences
        fields = [
            "new_episodes",
            "task_updates",
            "comment_replies",
            "comment_likes",
            "coin_earnings",
            "badges",
            "platform_announcements",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class NotificationItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    type = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    data = serializers.JSONField(
        help_text=(
            "Deep-link payload. Common keys by type: "
            "`followed_creator_new_episode` / `new_comment_on_episode`: "
            "episode_id, creator_id; "
            "`new_season_from_followed_creator`: season_id, creator_id, skillworld; "
            "`task_reminder` / `task_approved_with_coins` / `task_rejected_with_feedback`: "  # noqa: E501
            "episode_id, submission_id; "
            "`referral_bonus_credited`: transaction_id; "
            "`platform_announcement`: event_type."
        )
    )
    is_read = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class NotificationListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = NotificationItemSerializer(many=True)
    next = serializers.URLField(allow_null=True, required=False)
    offset = serializers.IntegerField()
    limit = serializers.IntegerField()


class LeaderboardResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True, required=False)
    previous = serializers.URLField(allow_null=True, required=False)
    my_position = UserLeaderboardEntrySerializer(allow_null=True, required=False)
    results = UserLeaderboardEntrySerializer(many=True)
