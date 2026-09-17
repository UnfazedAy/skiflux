from rest_framework import serializers

from skiflux.models.content import EpisodeComment
from skiflux.models.moderation import (
    CommentReport,
    ModerationActionLog,
    UserSuspension,
)


# ─────────────────────────────────────────
# Stats
# ─────────────────────────────────────────


class ModerationStatsSerializer(serializers.Serializer):
    flagged_today = serializers.IntegerField()
    resolved_today = serializers.IntegerField()
    active_suspensions = serializers.IntegerField()
    total_reports_this_week = serializers.IntegerField()
    reports_vs_last_week_pct = serializers.FloatField(allow_null=True)


# ─────────────────────────────────────────
# Shared nested serializers
# ─────────────────────────────────────────


class CommentUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    username = serializers.CharField(allow_null=True)
    avatar_url = serializers.CharField(allow_null=True)


class CommentEpisodeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    order = serializers.IntegerField()
    season_title = serializers.SerializerMethodField()

    def get_season_title(self, obj):
        return obj.season.title if obj.season else None


class FlaggedCommentActionSerializer(serializers.Serializer):
    ACTION_CHOICES = ["delete", "warn", "suspend", "dismiss"]

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    # warn fields
    category = serializers.CharField(required=False, allow_blank=True)
    message = serializers.CharField(required=False, allow_blank=True)

    # suspend fields
    duration_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Number of days to suspend. Null = permanent.",
    )

    def validate(self, data):
        action = data.get("action")

        if action == "warn":
            if not data.get("category"):
                raise serializers.ValidationError(
                    {"category": "Category is required for warn action."}
                )
            if not data.get("message"):
                raise serializers.ValidationError(
                    {"message": "Message is required for warn action."}
                )

        if action == "suspend" and "duration_days" not in data:
            raise serializers.ValidationError(
                {"duration_days": "duration_days is required for suspend action."}
            )

        return data


# ─────────────────────────────────────────
# All Comments
# ─────────────────────────────────────────


class CommentListSerializer(serializers.ModelSerializer):
    user = CommentUserSerializer(read_only=True)
    episode = CommentEpisodeSerializer(read_only=True)
    report_count = serializers.IntegerField(default=0)
    likes_count = serializers.IntegerField(default=0)

    class Meta:
        model = EpisodeComment
        fields = [
            "id",
            "user",
            "episode",
            "text",
            "flagged",
            "likes_count",
            "report_count",
            "created_at",
        ]


# ─────────────────────────────────────────
# Suspensions
# ─────────────────────────────────────────


class SuspendedUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    username = serializers.CharField(allow_null=True)
    email = serializers.CharField(allow_null=True)
    avatar_url = serializers.CharField(allow_null=True)


class SuspendedBySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class UserSuspensionSerializer(serializers.ModelSerializer):
    user = SuspendedUserSerializer(read_only=True)
    suspended_by = SuspendedBySerializer(read_only=True)
    display_duration = serializers.CharField(read_only=True)
    is_permanent = serializers.BooleanField(read_only=True)
    suspended_by_label = serializers.SerializerMethodField()

    class Meta:
        model = UserSuspension
        fields = [
            "id",
            "user",
            "suspended_by",
            "suspended_by_label",
            "source",
            "reason",
            "duration_days",
            "display_duration",
            "is_permanent",
            "expires_at",
            "status",
            "lifted_by",
            "lifted_at",
            "created_at",
        ]

    def get_suspended_by_label(self, obj):
        if obj.source == UserSuspension.SuspendedBySource.AI:
            return "Moderator (Auto)"
        if obj.suspended_by:
            return (
                f"Admin {obj.suspended_by.first_name} {obj.suspended_by.last_name}"
            ).strip()
        return "Unknown"


class LiftSuspensionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


# ─────────────────────────────────────────
# Action Log
# ─────────────────────────────────────────


class ActionLogPerformedBySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class ActionLogCommentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    text = serializers.CharField()
    episode_title = serializers.SerializerMethodField()
    season_title = serializers.SerializerMethodField()

    def get_episode_title(self, obj):
        return obj.episode.title if obj.episode else None

    def get_season_title(self, obj):
        return obj.episode.season.title if obj.episode and obj.episode.season else None


class ModerationActionLogSerializer(serializers.ModelSerializer):
    performed_by = ActionLogPerformedBySerializer(read_only=True)
    target_user = SuspendedUserSerializer(read_only=True)
    comment = ActionLogCommentSerializer(read_only=True)
    performed_by_label = serializers.SerializerMethodField()

    class Meta:
        model = ModerationActionLog
        fields = [
            "id",
            "action_type",
            "source",
            "performed_by",
            "performed_by_label",
            "target_user",
            "comment",
            "reason",
            "metadata",
            "created_at",
        ]

    def get_performed_by_label(self, obj):
        if obj.source == ModerationActionLog.Source.AI:
            return "Moderator (Auto)"
        if obj.performed_by:
            return f"{obj.performed_by.first_name} {obj.performed_by.last_name}".strip()
        return "Unknown"


# ─────────────────────────────────────────
# Report comment (learner side)
# ─────────────────────────────────────────


class ReportCommentSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=CommentReport.Category.choices)


class ReportedUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    username = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)


class FlaggedCommentSeasonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    skillworld = serializers.CharField()


class FlaggedCommentEpisodeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    season = FlaggedCommentSeasonSerializer()


class ReporterSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class CommentReportSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    category = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    reported_by = ReporterSerializer()


class FlaggedCommentSerializer(serializers.ModelSerializer):
    user = ReportedUserSerializer(read_only=True)
    episode = FlaggedCommentEpisodeSerializer(read_only=True)

    report_count = serializers.IntegerField(read_only=True)
    pending_report_count = serializers.IntegerField(read_only=True)
    likes_count = serializers.IntegerField(read_only=True)

    reports = CommentReportSerializer(many=True, read_only=True)
    report_category_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = EpisodeComment
        fields = [
            "id",
            "text",
            "audio_public_id",
            "flagged",
            "flagged_at",
            "created_at",
            "user",
            "episode",
            "report_count",
            "pending_report_count",
            "likes_count",
            "reports",
            "report_category_breakdown",
        ]

    def get_report_category_breakdown(self, obj):
        """
        Computed from the prefetched `reports` relation — no extra queries.
        """
        counts: dict[str, int] = {}
        for report in obj.reports.all():
            counts[report.category] = counts.get(report.category, 0) + 1

        return [
            {"category": category, "count": count}
            for category, count in sorted(
                counts.items(), key=lambda item: item[1], reverse=True
            )
        ]
