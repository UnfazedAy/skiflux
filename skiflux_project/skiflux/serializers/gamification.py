from django.utils.text import slugify
from rest_framework import serializers

from skiflux.models.gamification import Badge, PlatformTask, UserBadge, UserPlatformTask
from skiflux.utils import get_private_avatar_url


class BadgeSerializer(serializers.ModelSerializer):
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Badge
        fields = [
            "id",
            "name",
            "description",
            "icon_url",
            "is_active",
            "created_at",
        ]

    def get_icon_url(self, obj) -> str | None:
        return get_private_avatar_url(obj.icon_public_id)


class BadgeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = ["name", "description", "is_active"]


class PlatformTaskAdminSerializer(serializers.ModelSerializer):
    trigger_type = serializers.ChoiceField(
        choices=PlatformTask.TriggerType.choices,
        required=False,
        allow_blank=True,
        default="",
    )
    action_type = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
    )
    action_type_display = serializers.CharField(
        source="trigger_type",
        read_only=True,
    )

    class Meta:
        model = PlatformTask
        fields = [
            "id",
            "slug",
            "title",
            "description",
            "category",
            "trigger_type",
            "action_type",
            "action_type_display",
            "verification_mode",
            "progress_target",
            "duration_minutes",
            "external_url",
            "icon",
            "metadata",
            "sort_order",
            "xp_reward",
            "skillcoin_reward",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        action_type = attrs.pop("action_type", None)
        if action_type is not None and "trigger_type" not in attrs:
            attrs["trigger_type"] = action_type

        trigger_type = attrs.get(
            "trigger_type",
            getattr(self.instance, "trigger_type", ""),
        )
        if trigger_type:
            attrs.setdefault(
                "verification_mode", PlatformTask.VerificationMode.AUTOMATIC
            )
        else:
            attrs["verification_mode"] = PlatformTask.VerificationMode.MANUAL
        return attrs

    def validate_slug(self, value):
        if value:
            return slugify(value)
        return value


class PlatformTaskCreateSerializer(PlatformTaskAdminSerializer):
    slug = serializers.SlugField(required=False, allow_blank=True)

    def create(self, validated_data):
        service = self.context["service"]
        return service.create_task(validated_data)

    def update(self, instance, validated_data):
        service = self.context["service"]
        return service.update_task(str(instance.id), validated_data)


class OptionalBooleanQueryParamField(serializers.BooleanField):
    """Avoid treating a missing query param as False."""

    def get_value(self, dictionary):
        if "is_active" not in dictionary:
            return serializers.empty
        return super().get_value(dictionary)


class PlatformTaskListFilterSerializer(serializers.Serializer):
    is_active = OptionalBooleanQueryParamField(required=False)
    category = serializers.ChoiceField(
        choices=PlatformTask.Category.choices,
        required=False,
    )
    search = serializers.CharField(required=False, allow_blank=True)


class PlatformTaskUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.SlugField()
    title = serializers.CharField()
    description = serializers.CharField()
    category = serializers.CharField()
    trigger_type = serializers.CharField()
    action_type = serializers.CharField(required=False)
    verification_mode = serializers.CharField()
    progress_target = serializers.IntegerField()
    progress_current = serializers.IntegerField()
    duration_minutes = serializers.IntegerField(allow_null=True)
    external_url = serializers.URLField(allow_null=True)
    icon = serializers.CharField(allow_null=True)
    metadata = serializers.DictField()
    sort_order = serializers.IntegerField()
    xp_reward = serializers.IntegerField()
    skillcoin_reward = serializers.DecimalField(max_digits=10, decimal_places=2)
    is_active = serializers.BooleanField()
    status = serializers.CharField()
    claimable = serializers.BooleanField()
    completed = serializers.BooleanField()
    started_at = serializers.DateTimeField(allow_null=True)
    claimable_at = serializers.DateTimeField(allow_null=True)
    claimed_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class UserBadgeSerializer(serializers.ModelSerializer):
    badge = BadgeSerializer(read_only=True)

    class Meta:
        model = UserBadge
        fields = ["id", "badge", "earned_at"]


class StreakWeekDaySerializer(serializers.Serializer):
    weekday = serializers.CharField()
    date = serializers.DateField()
    day_of_month = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["completed", "missed", "upcoming"])


class StreakWeekSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    label = serializers.CharField()
    days = StreakWeekDaySerializer(many=True)


class StreakMilestoneSerializer(serializers.Serializer):
    interval_days = serializers.IntegerField()
    xp_reward = serializers.IntegerField()
    next_at_streak = serializers.IntegerField()
    days_remaining = serializers.IntegerField()
    reached_today = serializers.BooleanField()


class StreakSummarySerializer(serializers.Serializer):
    current_streak_count = serializers.IntegerField()
    is_streak_active = serializers.BooleanField()
    best_streak = serializers.IntegerField()
    total_streak_xp_earned = serializers.IntegerField()
    week = StreakWeekSerializer()
    milestone = StreakMilestoneSerializer()


class UserPlatformTaskSerializer(serializers.ModelSerializer):
    platform_task = PlatformTaskUserSerializer(source="*", read_only=True)

    class Meta:
        model = UserPlatformTask
        fields = ["id", "platform_task", "status", "claimed_at"]
