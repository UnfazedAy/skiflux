import uuid

from django.db import models


class InvestorReview(models.Model):
    class ChequeSize(models.TextChoices):
        FIVE_K_TEN_K = "5k_10k", "$5K–$10K"
        TEN_K_TWENTY_FIVE_K = "10k_25k", "$10K–$25K"
        TWENTY_FIVE_K_FIFTY_K = "25k_50k", "$25K–$50K"
        FIFTY_K_HUNDRED_K = "50k_100k", "$50K–$100K"
        HUNDRED_K_TWO_FIFTY_K = "100k_250k", "$100K–$250K"
        TWO_FIFTY_K_PLUS = "250k_plus", "$250K+"

    class DecisionTimeline(models.TextChoices):
        WITHIN_24_48_HOURS = "within_24_48_hours", "Within 24–48 Hours"
        WITHIN_1_WEEK = "within_1_week", "Within 1 Week"
        WITHIN_2_WEEKS = "within_2_weeks", "Within 2 Weeks"
        WITHIN_30_DAYS = "within_30_days", "Within 30 Days"

    class DeckPreference(models.TextChoices):
        SKIFLUX_DECK_V1_1 = "skiflux_deck_v1_1", "Skiflux Deck V1.1"
        SKIFLUX_DECK = "skiflux_deck", "Skiflux Deck"
        BOTH = "both", "Both"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(db_index=True)
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    investor_type = models.CharField(max_length=50, default="Investor")
    cheque_size = models.CharField(max_length=32, choices=ChequeSize.choices)
    decision_timeline = models.CharField(
        max_length=32,
        choices=DecisionTimeline.choices,
    )
    deck_preference = models.CharField(max_length=32, choices=DeckPreference.choices)
    scheduling_note = models.CharField(
        max_length=255,
        default="Calendly 30-minute investor call",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["-submitted_at"]),
            models.Index(fields=["email", "-submitted_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    @property
    def cheque_size_label(self) -> str:
        return self.ChequeSize(self.cheque_size).label

    @property
    def decision_timeline_label(self) -> str:
        return self.DecisionTimeline(self.decision_timeline).label

    @property
    def deck_preference_label(self) -> str:
        return self.DeckPreference(self.deck_preference).label
