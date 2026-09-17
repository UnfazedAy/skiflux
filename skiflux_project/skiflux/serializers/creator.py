from rest_framework import serializers
from skiflux.models import AdminUser
from skiflux.utils import get_private_avatar_url
from skiflux.repositories.content_repository import ContentRepository


class CreatorListSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The unique ID of the creator.")
    username = serializers.CharField(help_text="The username of the creator.")


class FollowedCreatorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField(allow_blank=True)
    username = serializers.CharField(allow_null=True)
    avatar_public_id = serializers.CharField(allow_null=True)
    bio = serializers.CharField(allow_blank=True, allow_null=True)
    skillworld = serializers.CharField(allow_null=True)
    followers_count = serializers.IntegerField(read_only=True)


class CreatorOversightEpisodeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    status = serializers.CharField()


class CreatorOversightResponseSerializer(serializers.Serializer):
    creator_id = serializers.UUIDField()
    episodes_count = serializers.IntegerField(
        help_text="Total number of episodes by this creator."
    )
    episodes = CreatorOversightEpisodeSerializer(many=True)


class CreatorProfileStatsSerializer(serializers.Serializer):
    seasons_count = serializers.IntegerField()
    episodes_count = serializers.IntegerField()
    submissions_count = serializers.IntegerField()
    subscribers_count = serializers.IntegerField()
    sla_avg = serializers.FloatField(allow_null=True, required=False)


class CreatorProfileResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    username = serializers.CharField(allow_null=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField(allow_blank=True)
    bio = serializers.CharField(allow_blank=True, allow_null=True)
    avatar_url = serializers.CharField(allow_null=True)
    display_name = serializers.CharField(allow_null=True)
    role_type = serializers.CharField()
    is_active = serializers.BooleanField()
    is_verified = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    stats = CreatorProfileStatsSerializer()


class CreatorProfileCompletionSerializer(serializers.Serializer):
    is_complete = serializers.BooleanField()
    missing_fields = serializers.ListField(child=serializers.CharField())
    can_use_studio = serializers.BooleanField()
    is_verified = serializers.BooleanField()


class OverrideEpisodeRequestSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField(help_text="The ID of the episode to override.")
    action = serializers.ChoiceField(
        choices=["unpublish"],
        help_text="The administrative action to apply to the episode.",
    )


class CreatorEpisodeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    description = serializers.CharField()
    status = serializers.CharField()
    view_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    access_type = serializers.CharField()
    thumbnail_url = serializers.SerializerMethodField()

    def get_thumbnail_url(self, obj) -> str | None:
        if obj.thumbnail_public_id:
            return get_private_avatar_url(obj.thumbnail_public_id)
        return None


class CreatorEpisodeListResponseSerializer(serializers.Serializer):
    creator_id = serializers.UUIDField()
    videos_count = serializers.IntegerField()
    videos = CreatorEpisodeSerializer(many=True)


class CreatorEpisodeListRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["draft", "published"],
        required=False,
        help_text="Filter episodes by status (optional).",
    )


class CreatorAnalyticsResponseSerializer(serializers.Serializer):
    total_episodes = serializers.IntegerField()
    new_episodes_this_month = serializers.IntegerField()
    episodes_growth_percentage = serializers.DecimalField(
        max_digits=9, decimal_places=1
    )
    total_followers = serializers.IntegerField()
    new_followers_this_month = serializers.IntegerField()
    followers_growth_percentage = serializers.DecimalField(
        max_digits=9, decimal_places=1
    )
    total_earnings = serializers.DecimalField(max_digits=10, decimal_places=2)
    avg_rating = serializers.DecimalField(
        max_digits=3, decimal_places=1, allow_null=True
    )
    total_ratings = serializers.IntegerField()


class ToggleFollowResponseSerializer(serializers.Serializer):
    creator_id = serializers.UUIDField()
    is_following = serializers.BooleanField()
    followers_count = serializers.IntegerField()


class PublicCreatorProfileSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField(allow_null=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_null=True, allow_blank=True)
    avatar_url = serializers.CharField(allow_null=True)
    bio = serializers.CharField(allow_blank=True, allow_null=True)
    skillworld = serializers.CharField(allow_null=True)
    followers_count = serializers.IntegerField()
    is_following = serializers.BooleanField()
    notification_mode = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Present when is_following is true.",
    )


class EpisodeRatingRequestSerializer(serializers.Serializer):
    score = serializers.IntegerField(
        min_value=1,
        max_value=5,
        help_text="Rating score from 1 to 5.",
    )
    review = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional review text.",
    )


class EpisodeRatingResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    episode_id = serializers.UUIDField()
    score = serializers.IntegerField()
    review = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class CreatorProfileUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(
        required=False, allow_blank=False, allow_null=True
    )
    last_name = serializers.CharField(
        required=False, allow_blank=False, allow_null=True
    )
    username = serializers.CharField(
        max_length=20, required=False, help_text="Unique creator handle."
    )
    bio = serializers.CharField(
        max_length=1000, required=False, help_text="Creator professional bio."
    )
    display_name = serializers.CharField(
        max_length=255, required=False, help_text="Creator display name."
    )
    avatar_file = serializers.ImageField(
        required=False, help_text="Profile picture image file."
    )

    def validate(self, data):
        # Ensure at least one field is provided
        msg = (
            "At least one of first_name, "
            "last_name, username, bio, display_name, or avatar_file "
            "must be provided."
        )
        if not any(
            [
                data.get("first_name"),
                data.get("last_name"),
                data.get("username"),
                data.get("bio"),
                data.get("avatar_file"),
                data.get("display_name"),
            ]
        ):
            raise serializers.ValidationError({"detail": msg})
        return data


class CreatorDirectoryStatsSerializer(serializers.Serializer):
    total_creators = serializers.IntegerField()
    new_creators_this_month = serializers.IntegerField()
    growth_percentage_this_month = serializers.DecimalField(
        max_digits=5, decimal_places=1
    )
    active_today = serializers.IntegerField()
    new_this_week = serializers.IntegerField()
    avg_uploads_per_creator_this_week = serializers.DecimalField(
        max_digits=5, decimal_places=1
    )
    pending_submissions = serializers.IntegerField()
    avg_sla_rate = serializers.DecimalField(max_digits=5, decimal_places=1)


class CreatorDirectoryItemSerializer(serializers.Serializer):
    def get_avatar_url(self, obj) -> str | None:
        if obj.avatar_public_id:
            return get_private_avatar_url(obj.avatar_public_id)
        return None

    def get_sla_rate(self, obj) -> float:
        return ContentRepository().get_average_sla_by_creator(obj)

    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    username = serializers.CharField(allow_null=True)
    email = serializers.EmailField()
    avatar_public_id = serializers.CharField(allow_null=True)
    avatar_url = serializers.SerializerMethodField()
    skillworld = serializers.CharField(allow_null=True)
    seasons_count = serializers.IntegerField()
    episode_count = serializers.IntegerField()
    earnings = serializers.DecimalField(max_digits=10, decimal_places=2)
    status = serializers.ChoiceField(
        choices=[
            AdminUser.Status.ACTIVE,
            AdminUser.Status.SUSPENDED,
            AdminUser.Status.DEACTIVATED,
        ]
    )
    pending_reviews = serializers.IntegerField()
    sla_rate = serializers.SerializerMethodField()


class CreatorDirectoryRequestSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(
        choices=[
            AdminUser.Status.ACTIVE,
            AdminUser.Status.SUSPENDED,
            AdminUser.Status.DEACTIVATED,
        ],
        required=False,
    )
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    page = serializers.CharField(required=False)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"date_to": "date_to must be after date_from."}
            )
        return attrs


class CreatorLeaderBoardSerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    username = serializers.CharField(allow_null=True)
    avatar_public_id = serializers.CharField(allow_null=True)
    episodes_count = serializers.IntegerField()
    episodes_count_trend_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=1
    )


class AudienceDistributionSerializer(serializers.Serializer):
    country = serializers.CharField()
    pct = serializers.IntegerField()


class RevenueGrowthSerializer(serializers.Serializer):
    labels = serializers.ListField(child=serializers.CharField())
    current = serializers.ListField(child=serializers.FloatField())
    previous = serializers.ListField(child=serializers.FloatField())
