from django.db import transaction

from skiflux.models.investor import InvestorReview
from skiflux.repositories.investor_repository import InvestorRepository
from skiflux.utils.investor_emails import send_investor_confirmation_email

SCHEDULING_NOTE = "Calendly 30-minute investor call"
INVESTOR_TYPE = "Investor"


class InvestorService:
    def __init__(self):
        self.repo = InvestorRepository()

    def submit_review(self, data: dict) -> InvestorReview:
        with transaction.atomic():
            review = self.repo.create(
                full_name=data["full_name"],
                email=data["email"],
                country=data["country"],
                city=data["city"],
                investor_type=INVESTOR_TYPE,
                cheque_size=data["cheque_size"],
                decision_timeline=data["decision_timeline"],
                deck_preference=data["deck_preference"],
                scheduling_note=SCHEDULING_NOTE,
            )

        send_investor_confirmation_email(review)
        return review

    def list_reviews(self, email: str | None = None):
        return self.repo.list_queryset(email=email)

    @staticmethod
    def serialize_review(review: InvestorReview) -> dict:
        return {
            "id": review.id,
            "full_name": review.full_name,
            "email": review.email,
            "country": review.country,
            "city": review.city,
            "investor_type": review.investor_type,
            "cheque_size": review.cheque_size_label,
            "decision_timeline": review.decision_timeline_label,
            "deck_preference": review.deck_preference_label,
            "scheduling_note": review.scheduling_note,
            "submitted_at": review.submitted_at,
        }
