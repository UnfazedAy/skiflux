from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from skiflux.models import InvestorReview, Permission

from .conftest import admin_auth_client, make_admin_with_role, make_super_admin

BASE = "/api/v1"

VALID_PAYLOAD = {
    "full_name": "Ayomide Soniyi",
    "email": "ayomidesoniyi@gmail.com",
    "country": "Nigeria",
    "city": "Lagos",
    "cheque_size": "100k_250k",
    "decision_timeline": "within_1_week",
    "deck_preference": "skiflux_deck_v1_1",
}


class InvestorReviewSubmitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    @patch("skiflux.utils.investor_emails.send_app_email_task.apply_async")
    def test_submit_success_returns_201_and_persists(self, mock_email):
        resp = self.client.post(
            f"{BASE}/investor/review/",
            VALID_PAYLOAD,
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], "success")
        self.assertEqual(
            InvestorReview.objects.filter(email="ayomidesoniyi@gmail.com").count(),
            1,
        )

        data = resp.data["data"]
        self.assertEqual(data["full_name"], "Ayomide Soniyi")
        self.assertEqual(data["email"], "ayomidesoniyi@gmail.com")
        self.assertEqual(data["investor_type"], "Investor")
        self.assertEqual(data["cheque_size"], "$100K–$250K")
        self.assertEqual(data["decision_timeline"], "Within 1 Week")
        self.assertEqual(data["deck_preference"], "Skiflux Deck V1.1")
        self.assertEqual(data["scheduling_note"], "Calendly 30-minute investor call")
        mock_email.assert_called_once()

    def test_submit_missing_fields_returns_400(self):
        resp = self.client.post(f"{BASE}/investor/review/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["status"], "error")

    def test_submit_invalid_enum_returns_400(self):
        payload = {**VALID_PAYLOAD, "cheque_size": "invalid_size"}
        resp = self.client.post(f"{BASE}/investor/review/", payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_submit_invalid_email_returns_400(self):
        payload = {**VALID_PAYLOAD, "email": "not-an-email"}
        resp = self.client.post(f"{BASE}/investor/review/", payload, format="json")
        self.assertEqual(resp.status_code, 400)

    @patch("skiflux.utils.investor_emails.send_app_email_task.apply_async")
    def test_submit_normalizes_email_to_lowercase(self, mock_email):
        payload = {**VALID_PAYLOAD, "email": "MixedCase@Example.COM"}
        resp = self.client.post(f"{BASE}/investor/review/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["data"]["email"], "mixedcase@example.com")
        review = InvestorReview.objects.get(email="mixedcase@example.com")
        self.assertEqual(review.email, "mixedcase@example.com")
        mock_email.assert_called_once()

    @patch("skiflux.utils.investor_emails.send_app_email_task.apply_async")
    def test_duplicate_email_allowed(self, mock_email):
        self.client.post(f"{BASE}/investor/review/", VALID_PAYLOAD, format="json")
        resp = self.client.post(
            f"{BASE}/investor/review/", VALID_PAYLOAD, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            InvestorReview.objects.filter(email="ayomidesoniyi@gmail.com").count(),
            2,
        )


class InvestorReviewAdminListTests(TestCase):
    def setUp(self):
        InvestorReview.objects.create(
            full_name="Ayomide Soniyi",
            email="ayomidesoniyi@gmail.com",
            country="Nigeria",
            city="Lagos",
            cheque_size=InvestorReview.ChequeSize.HUNDRED_K_TWO_FIFTY_K,
            decision_timeline=InvestorReview.DecisionTimeline.WITHIN_1_WEEK,
            deck_preference=InvestorReview.DeckPreference.SKIFLUX_DECK_V1_1,
        )

    def test_admin_list_requires_authentication(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/investor-reviews/")
        self.assertEqual(resp.status_code, 403)

    def test_admin_list_without_permission_returns_403(self):
        admin, _role = make_admin_with_role([Permission.USERS_VIEW])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/investor-reviews/")
        self.assertEqual(resp.status_code, 403)

    def test_super_admin_can_list_reviews(self):
        admin = make_super_admin()
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/investor-reviews/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)
        self.assertEqual(len(resp.data["data"]["results"]), 1)
        self.assertEqual(
            resp.data["data"]["results"][0]["email"],
            "ayomidesoniyi@gmail.com",
        )

    def test_admin_list_filters_by_email(self):
        InvestorReview.objects.create(
            full_name="Other Person",
            email="other@example.com",
            country="UK",
            city="London",
            cheque_size=InvestorReview.ChequeSize.FIVE_K_TEN_K,
            decision_timeline=InvestorReview.DecisionTimeline.WITHIN_2_WEEKS,
            deck_preference=InvestorReview.DeckPreference.BOTH,
        )
        admin = make_super_admin()
        client = admin_auth_client(admin)
        resp = client.get(
            f"{BASE}/admin/investor-reviews/",
            {"email": "other@example.com"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["count"], 1)
        self.assertEqual(resp.data["data"]["results"][0]["email"], "other@example.com")
