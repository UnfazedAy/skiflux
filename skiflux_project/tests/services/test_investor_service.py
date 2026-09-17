from unittest.mock import patch

from django.test import TestCase

from skiflux.models.investor import InvestorReview
from skiflux.services.investor_service import InvestorService


class InvestorServiceTests(TestCase):
    @patch("skiflux.utils.investor_emails.send_app_email_task.apply_async")
    def test_submit_review_creates_record_with_fixed_fields(self, mock_email):
        service = InvestorService()
        review = service.submit_review(
            {
                "full_name": "Ayomide Soniyi",
                "email": "ayomidesoniyi@gmail.com",
                "country": "Nigeria",
                "city": "Lagos",
                "cheque_size": InvestorReview.ChequeSize.HUNDRED_K_TWO_FIFTY_K,
                "decision_timeline": InvestorReview.DecisionTimeline.WITHIN_1_WEEK,
                "deck_preference": InvestorReview.DeckPreference.SKIFLUX_DECK_V1_1,
            }
        )

        self.assertEqual(review.investor_type, "Investor")
        self.assertEqual(review.scheduling_note, "Calendly 30-minute investor call")
        mock_email.assert_called_once()

    @patch("skiflux.utils.investor_emails.send_app_email_task.apply_async")
    def test_serialize_review_returns_display_labels(self, mock_email):
        service = InvestorService()
        review = service.submit_review(
            {
                "full_name": "Ayomide Soniyi",
                "email": "ayomidesoniyi@gmail.com",
                "country": "Nigeria",
                "city": "Lagos",
                "cheque_size": InvestorReview.ChequeSize.HUNDRED_K_TWO_FIFTY_K,
                "decision_timeline": InvestorReview.DecisionTimeline.WITHIN_1_WEEK,
                "deck_preference": InvestorReview.DeckPreference.SKIFLUX_DECK_V1_1,
            }
        )

        data = service.serialize_review(review)
        self.assertEqual(data["cheque_size"], "$100K–$250K")
        self.assertEqual(data["decision_timeline"], "Within 1 Week")
        self.assertEqual(data["deck_preference"], "Skiflux Deck V1.1")

    @patch("skiflux.utils.investor_emails.send_app_email_task.apply_async")
    def test_confirmation_email_includes_html(self, mock_email):
        service = InvestorService()
        review = service.submit_review(
            {
                "full_name": "Ayomide Soniyi",
                "email": "ayomidesoniyi@gmail.com",
                "country": "Nigeria",
                "city": "Lagos",
                "cheque_size": InvestorReview.ChequeSize.HUNDRED_K_TWO_FIFTY_K,
                "decision_timeline": InvestorReview.DecisionTimeline.WITHIN_1_WEEK,
                "deck_preference": InvestorReview.DeckPreference.SKIFLUX_DECK_V1_1,
            }
        )

        mock_email.assert_called_once()
        email_kwargs = mock_email.call_args.kwargs["kwargs"]
        self.assertIn("html_message", email_kwargs)
        self.assertIn("Skiflux Investor Review", email_kwargs["html_message"])
        self.assertIn(review.full_name, email_kwargs["html_message"])
