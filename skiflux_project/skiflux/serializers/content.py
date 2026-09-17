from rest_framework import serializers

from skiflux.models.content import Season
from skiflux.serializers.studio import EpisodeSerializer


class ApproveTaskSubmissionSerializer(serializers.Serializer):
    cashback_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class RejectTaskSubmissionSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(allow_blank=False, max_length=1000)
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class EpisodeReviewActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    rejection_reason = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=1000,
        help_text="Required when action is 'reject'.",
    )

    def validate(self, data):
        if data["action"] == "reject" and not data.get("rejection_reason"):
            raise serializers.ValidationError(
                {
                    "rejection_reason": "A rejection reason is required when rejecting an episode."  # noqa: E501
                }
            )
        return data


class EpisodeReviewListSerializer(EpisodeSerializer):
    """Full episode payload for the admin review queue list."""


class PlatformAnnouncementSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    body = serializers.CharField()
    image_public_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    send_type = serializers.ChoiceField(
        choices=["immediate", "daily"], default="immediate", required=False
    )
    daily_send_time = serializers.TimeField(required=False, allow_null=True)
    delivery_channel = serializers.ChoiceField(
        choices=["foreground", "background"],
        default="foreground",
        required=False,
    )
    audience = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="All users",
    )

    def get_creator_name(self, obj) -> str:
        from skiflux.utils.media import creator_display_name

        return creator_display_name(obj.creator)


class NotificationStatsSerializer(serializers.Serializer):
    total_sent = serializers.IntegerField()
    total_foreground = serializers.IntegerField()
    total_background = serializers.IntegerField()
    scheduled_pending = serializers.IntegerField()


class NotificationHistoryItemSerializer(serializers.Serializer):
    title = serializers.CharField()
    message = serializers.CharField()
    type = serializers.CharField()
    audience = serializers.CharField()
    send_time = serializers.DateTimeField()
    status = serializers.CharField()
    recipient_count = serializers.IntegerField()


class PaginatedNotificationHistorySerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = NotificationHistoryItemSerializer(many=True)


class ContentApprovalStatsSerializer(serializers.Serializer):
    pending_approval_count = serializers.IntegerField()
    approved_count = serializers.IntegerField()
    rejected_count = serializers.IntegerField()
    avg_review_hour = serializers.DecimalField(max_digits=3, decimal_places=1)


class ContentApprovalListSerializer(serializers.Serializer):
    episode_id = serializers.UUIDField()
    episode_title = serializers.CharField()
    creator_name = serializers.CharField()
    skillworld = serializers.CharField()
    season_title = serializers.CharField()
    status = serializers.CharField()
    task_type = serializers.CharField()
    submitted_at = serializers.DateTimeField()
    video_duration = serializers.CharField()


class SeasonPerformanceSerializer(serializers.ModelSerializer):
    released_at = serializers.SerializerMethodField()
    total_sales = serializers.IntegerField(default=0)
    cover_image_url = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()
    revenue = serializers.SerializerMethodField()
    avg_rating = serializers.SerializerMethodField()

    class Meta:
        model = Season
        fields = [
            "id",
            "title",
            "cover_image_public_id",
            "cover_image_url",
            "released_at",
            "total_sales",
            "completion_percentage",
            "revenue",
            "avg_rating",
        ]

    def get_released_at(self, obj):
        return obj.created_at

    def get_completion_percentage(self, obj):
        total = obj.total_viewers or 0
        completed = obj.completed_viewers or 0
        return round((completed / total) * 100) if total > 0 else 0

    def get_revenue(self, obj):
        return float(obj.revenue or 0)

    def get_cover_image_url(self, obj):
        if obj.cover_image_public_id:
            from skiflux.utils.media import get_private_media_url

            return get_private_media_url(obj.cover_image_public_id)
        return None

    def get_avg_rating(self, obj):
        return round(obj.avg_rating, 1) if obj.avg_rating else None
