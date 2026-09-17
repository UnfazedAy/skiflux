from rest_framework import serializers

from skiflux.models.activity import ActivityLog


class ActivityPrincipalSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    email = serializers.EmailField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_id(self, obj):
        return str(obj.id)

    def get_type(self, obj):
        return "admin" if obj.__class__.__name__ == "AdminUser" else "user"

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.email


class ActivityLogSerializer(serializers.ModelSerializer):
    action_type_display = serializers.CharField(
        source="get_action_type_display",
        read_only=True,
    )
    actor = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "action_type",
            "action_type_display",
            "description",
            "actor",
            "subject",
            "metadata",
            "timestamp",
        ]
        read_only_fields = fields

    def _serialize_principal(self, obj):
        if obj is None:
            return None
        return ActivityPrincipalSerializer(obj).data

    def get_actor(self, obj) -> dict:
        return self._serialize_principal(obj.actor_admin or obj.actor_user)

    def get_subject(self, obj) -> dict:
        return self._serialize_principal(obj.subject_admin or obj.subject_user)


class ActivityStatsSerializer(serializers.Serializer):
    total_activities = serializers.IntegerField()
    by_type = serializers.DictField()
    by_actor = serializers.DictField()
