from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from skiflux.models import AdminUser, User
from skiflux.models.content import Episode
from skiflux.models.role import Permission
from skiflux.models.wallet import SkillcoinTransaction
from skiflux.repositories.dashboard_repository import DashboardRepository
from skiflux.services.dashboard_service import DashboardService
from skiflux.services.wallet_service import WalletService

from .conftest import (
    admin_auth_client,
    anon_client,
    make_admin_with_role,
    make_creator,
    make_episode,
    make_season,
    make_super_admin,
    make_verified_user,
)

BASE = "/api/v1"


class DashboardOverviewRepositoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.repository = DashboardRepository()

    def test_revenue_last_24h_counts_only_recent_posted_platform_revenue(self):
        wallet_service = WalletService()
        wallet_service.credit_platform_wallet(
            Decimal("25.00"),
            SkillcoinTransaction.Type.PLATFORM_REVENUE,
            "Recent platform revenue",
        )
        old_wallet = wallet_service.credit_platform_wallet(
            Decimal("40.00"),
            SkillcoinTransaction.Type.PLATFORM_REVENUE,
            "Old platform revenue",
        )
        SkillcoinTransaction.objects.filter(
            wallet=old_wallet,
            description="Old platform revenue",
        ).update(created_at=timezone.now() - timedelta(days=2))

        wallet_service.credit_platform_wallet(
            Decimal("15.00"),
            SkillcoinTransaction.Type.CASHBACK_REWARD,
            "Not revenue",
        )

        self.assertEqual(
            self.repository.get_revenue_last_24h(),
            Decimal("25.00"),
        )

    def test_high_priority_pending_verifications_respects_review_sla(self):
        creator = make_creator()
        season = make_season(creator)
        old_episode = make_episode(
            creator,
            season,
            status=Episode.Status.REVIEW,
        )
        old_episode.submitted_for_review_at = timezone.now() - timedelta(days=3)
        old_episode.save(update_fields=["submitted_for_review_at"])

        make_episode(
            creator,
            season,
            title="Fresh Review",
            order=2,
            status=Episode.Status.REVIEW,
        )

        self.assertEqual(self.repository.count_pending_verifications(), 2)
        self.assertEqual(
            self.repository.count_high_priority_pending_verifications(),
            1,
        )


class DashboardOverviewServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_get_overview_returns_dashboard_serializer_payload(self):
        old_user = make_verified_user(email="old@example.com")
        User.objects.filter(id=old_user.id).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        make_verified_user(email="new@example.com")

        old_creator = make_creator(email="oldcreator@example.com", username="old")
        AdminUser.objects.filter(id=old_creator.id).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        make_creator(email="newcreator@example.com", username="new")

        WalletService().credit_platform_wallet(
            Decimal("12.50"),
            SkillcoinTransaction.Type.PLATFORM_REVENUE,
            "Recent revenue",
        )

        overview = DashboardService().get_overview()

        self.assertEqual(overview["total_users"], 2)
        self.assertEqual(overview["total_users_growth_percentage"], Decimal("100.0"))
        self.assertEqual(overview["active_creators"], 2)
        self.assertEqual(
            overview["active_creators_growth_percentage"],
            Decimal("100.0"),
        )
        self.assertEqual(overview["revenue_last_24h"], Decimal("12.50"))
        self.assertEqual(overview["pending_verifications"], 0)
        self.assertFalse(overview["is_pending_verifications_high_priority"])


class DashboardOverviewAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

    def test_dashboard_overview_as_super_admin_success(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/dashboard/overview")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        self.assertEqual(
            set(resp.data["data"].keys()),
            {
                "total_users",
                "total_users_growth_percentage",
                "active_creators",
                "active_creators_growth_percentage",
                "revenue_last_24h",
                "pending_verifications",
                "is_pending_verifications_high_priority",
            },
        )

    def test_dashboard_overview_admin_with_analytics_permission_success(self):
        admin, _ = make_admin_with_role([Permission.ANALYTICS_VIEW])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/dashboard/overview")

        self.assertEqual(resp.status_code, 200)

    def test_dashboard_overview_admin_without_permission_returns_403(self):
        admin, _ = make_admin_with_role([])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/dashboard/overview")

        self.assertEqual(resp.status_code, 403)

    def test_dashboard_overview_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/admin/dashboard/overview")

        self.assertEqual(resp.status_code, 403)


class UserGrowthRepositoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.repository = DashboardRepository()

    def test_returns_only_months_with_data(self):
        make_verified_user(email="user1@example.com")
        make_verified_user(email="user2@example.com")

        result = self.repository.get_user_growth_by_month(months=6)
        data = list(result["data"])

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["count"], 2)

    def test_excludes_users_outside_date_range(self):
        old_user = make_verified_user(email="old@example.com")
        User.objects.filter(id=old_user.id).update(
            created_at=timezone.now() - timedelta(days=200)
        )
        make_verified_user(email="recent@example.com")

        result = self.repository.get_user_growth_by_month(months=6)
        data = list(result["data"])

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["count"], 1)

    def test_percentage_change_increase(self):
        old_user = make_verified_user(email="old@example.com")
        User.objects.filter(id=old_user.id).update(
            created_at=timezone.now() - timedelta(days=400)
        )
        make_verified_user(email="recent1@example.com")
        make_verified_user(email="recent2@example.com")

        result = self.repository.get_user_growth_by_month(months=6)
        self.assertTrue(result["is_increase"])
        self.assertGreater(result["percentage_change"], 0)

    def test_percentage_change_when_no_previous_data(self):
        make_verified_user(email="user@example.com")

        result = self.repository.get_user_growth_by_month(months=6)

        self.assertEqual(result["percentage_change"], 100.0)
        self.assertTrue(result["is_increase"])

    def test_percentage_change_zero_when_no_data_at_all(self):
        result = self.repository.get_user_growth_by_month(months=6)

        self.assertEqual(result["percentage_change"], 0.0)
        self.assertFalse(result["is_increase"])

    def test_data_ordered_by_month_ascending(self):
        user1 = make_verified_user(email="user1@example.com")
        user2 = make_verified_user(email="user2@example.com")
        User.objects.filter(id=user1.id).update(
            created_at=timezone.now() - timedelta(days=60)
        )
        User.objects.filter(id=user2.id).update(
            created_at=timezone.now() - timedelta(days=10)
        )

        result = self.repository.get_user_growth_by_month(months=6)

        months = [entry["month"] for entry in result["data"]]
        self.assertEqual(months, sorted(months))


class UserGrowthServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_get_user_growth_delegates_to_repository(self):
        make_verified_user(email="user@example.com")

        result = DashboardService().get_user_growth(months=6)

        self.assertIn("data", result)
        self.assertIn("percentage_change", result)
        self.assertIn("is_increase", result)


class UserGrowthAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()

    def test_user_growth_as_super_admin_success(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/dashboard/user-growth")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")
        self.assertIn("data", resp.data["data"])
        self.assertIn("percentage_change", resp.data["data"])
        self.assertIn("is_increase", resp.data["data"])

    def test_user_growth_default_months_is_6(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/dashboard/user-growth")

        self.assertEqual(resp.status_code, 200)

    def test_user_growth_custom_months_param(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/dashboard/user-growth?months=3")

        self.assertEqual(resp.status_code, 200)

    def test_user_growth_invalid_months_param_defaults_to_6(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/dashboard/user-growth?months=abc")

        self.assertEqual(resp.status_code, 200)

    def test_user_growth_months_capped_at_24(self):
        client = admin_auth_client(self.super_admin)
        resp = client.get(f"{BASE}/admin/dashboard/user-growth?months=999")

        self.assertEqual(resp.status_code, 200)

    def test_user_growth_admin_with_analytics_permission_success(self):
        admin, _ = make_admin_with_role([Permission.ANALYTICS_VIEW])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/dashboard/user-growth")

        self.assertEqual(resp.status_code, 200)

    def test_user_growth_admin_without_permission_returns_403(self):
        admin, _ = make_admin_with_role([])
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/dashboard/user-growth")

        self.assertEqual(resp.status_code, 403)

    def test_user_growth_unauthenticated_returns_403(self):
        resp = anon_client().get(f"{BASE}/admin/dashboard/user-growth")

        self.assertEqual(resp.status_code, 403)
