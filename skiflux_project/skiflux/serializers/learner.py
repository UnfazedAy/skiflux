from rest_framework import serializers


class LearnerSuspendSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5)
    duration_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Number of days. Null = permanent.",
    )


class DeactivateUserSerializer(serializers.Serializer):
    reason = serializers.CharField(
        min_length=5,
        required=False,
        allow_blank=True,
        default="",
    )
