from rest_framework import serializers

from skiflux.models.investor import InvestorReview


class InvestorReviewSubmitSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=True, allow_blank=False, max_length=255)
    email = serializers.EmailField(required=True, allow_blank=False)
    country = serializers.CharField(required=True, allow_blank=False, max_length=100)
    city = serializers.CharField(required=True, allow_blank=False, max_length=100)
    cheque_size = serializers.ChoiceField(choices=InvestorReview.ChequeSize.choices)
    decision_timeline = serializers.ChoiceField(
        choices=InvestorReview.DecisionTimeline.choices
    )
    deck_preference = serializers.ChoiceField(
        choices=InvestorReview.DeckPreference.choices
    )

    def validate_email(self, value):
        return value.lower().strip()

    def validate_full_name(self, value):
        return value.strip()


class InvestorReviewResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    country = serializers.CharField()
    city = serializers.CharField()
    investor_type = serializers.CharField()
    cheque_size = serializers.CharField()
    decision_timeline = serializers.CharField()
    deck_preference = serializers.CharField()
    scheduling_note = serializers.CharField()
    submitted_at = serializers.DateTimeField()


class InvestorReviewListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    country = serializers.CharField()
    city = serializers.CharField()
    investor_type = serializers.CharField()
    cheque_size = serializers.CharField()
    decision_timeline = serializers.CharField()
    deck_preference = serializers.CharField()
    scheduling_note = serializers.CharField()
    submitted_at = serializers.DateTimeField()


class InvestorReviewFilterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_email(self, value):
        if value:
            return value.lower().strip()
        return value
