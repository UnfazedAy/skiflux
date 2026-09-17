"""
Admin Auth & RBAC Tests
Covers: admin login, token refresh, logout, role management,
        admin user CRUD, permission enforcement, privilege escalation.
"""

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta

from skiflux.models import AdminUser, User
from skiflux.models.role import Permission, Role
from skiflux.models.content import Episode
from skiflux.utils.auth import (
    create_admin_refresh_token,
    decode_token,
    set_password_reset_otp,
)

from .conftest import (
    admin_auth_client,
    make_admin_with_role,
    make_super_admin,
    make_season,
    make_creator,
    make_episode,
)

BASE = "/api/v1"


class AdminLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_super_admin()

    def test_admin_login_success(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/login",
            {
                "email": "superadmin@skiflux.com",
                "password": "AdminPass1!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.data["data"])

    def test_admin_login_wrong_password_returns_400(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/login",
            {
                "email": "superadmin@skiflux.com",
                "password": "WrongPassword!",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_login_nonexistent_email_returns_400(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/login",
            {
                "email": "ghost@skiflux.com",
                "password": "AdminPass1!",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_admin_login_missing_fields_returns_400(self):
        client = APIClient()
        resp = client.post(f"{BASE}/admin/auth/login", {"email": "a@b.com"})
        self.assertEqual(resp.status_code, 400)


class AdminTokenTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_super_admin()

    def test_admin_token_refresh_returns_admin_scoped_token(self):
        """Regression: refresh must return an admin-scoped token, not a user token."""
        refresh = create_admin_refresh_token(str(self.admin.id))
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/token/refresh",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp.status_code, 200)
        new_access = resp.data["data"]["access_token"]
        payload = decode_token(new_access, scope="admin")
        self.assertEqual(payload.get("scope"), "admin")
        self.assertIn("admin_id", payload)
        self.assertNotIn("user_id", payload)

    def test_admin_refresh_with_invalid_token_returns_401(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/token/refresh",
            {"refresh_token": "invalid-token"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_admin_refresh_token_single_use(self):
        """Admin refresh tokens must be blacklisted after use."""
        refresh = create_admin_refresh_token(str(self.admin.id))
        client = APIClient()
        resp1 = client.post(
            f"{BASE}/admin/auth/token/refresh",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp1.status_code, 200)
        resp2 = client.post(
            f"{BASE}/admin/auth/token/refresh",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp2.status_code, 401)

    def test_admin_logout_success(self):
        refresh = create_admin_refresh_token(str(self.admin.id))
        client = admin_auth_client(self.admin)
        resp = client.post(
            f"{BASE}/admin/auth/logout",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_logout_requires_authentication(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/logout",
            {"refresh_token": "anything"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_user_token_rejected_on_admin_endpoint(self):
        """Security: user-scoped tokens must not work on admin routes."""
        from skiflux.models import User
        from skiflux.utils.auth import create_access_token

        user = User.objects.create_user(
            email="user@example.com",
            first_name="U",
            password="StrongPass1!",
        )
        token = create_access_token(str(user.id))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = client.get(f"{BASE}/admin/users")
        self.assertEqual(resp.status_code, 403)


class AdminForgotPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_super_admin()

    def test_admin_forgot_password_always_returns_200(self):
        """Security: must not leak whether admin email exists."""
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/forgot-password",
            {"email": "nonexistent-admin@example.com"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_verify_password_otp_success(self):
        set_password_reset_otp(self.admin.email, "654321")
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/verify-forgot-password-otp",
            {"email": self.admin.email, "otp": "654321"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_admin_reset_password_success(self):
        set_password_reset_otp(self.admin.email, "111111")
        client = APIClient()
        client.post(
            f"{BASE}/admin/auth/verify-forgot-password-otp",
            {"email": self.admin.email, "otp": "111111"},
        )
        resp = client.post(
            f"{BASE}/admin/auth/reset-password",
            {
                "email": self.admin.email,
                "otp": "111111",
                "new_password": "NewAdminPass1!",
                "confirm_new_password": "NewAdminPass1!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("NewAdminPass1!"))


class AdminChangePasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_super_admin()
        self.client = admin_auth_client(self.admin)

    def test_admin_change_password_success(self):
        resp = self.client.post(
            f"{BASE}/admin/auth/change-password",
            {
                "current_password": "AdminPass1!",
                "new_password": "NewAdminPass2!",
                "confirm_new_password": "NewAdminPass2!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("NewAdminPass2!"))

    def test_admin_change_password_wrong_current_password_returns_400(self):
        resp = self.client.post(
            f"{BASE}/admin/auth/change-password",
            {
                "current_password": "WrongPassword!",
                "new_password": "NewAdminPass2!",
                "confirm_new_password": "NewAdminPass2!",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("current_password", resp.data["message"])

    def test_admin_change_password_mismatch_returns_400(self):
        resp = self.client.post(
            f"{BASE}/admin/auth/change-password",
            {
                "current_password": "AdminPass1!",
                "new_password": "NewAdminPass2!",
                "confirm_new_password": "DifferentPass2!",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("confirm_new_password", resp.data["message"])

    def test_admin_change_password_requires_authentication(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/admin/auth/change-password",
            {
                "current_password": "AdminPass1!",
                "new_password": "NewAdminPass2!",
                "confirm_new_password": "NewAdminPass2!",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_change_password_weak_password_returns_400(self):
        resp = self.client.post(
            f"{BASE}/admin/auth/change-password",
            {
                "current_password": "AdminPass1!",
                "new_password": "weak",
                "confirm_new_password": "weak",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("new_password", resp.data["message"])


class PermissionListTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.client = admin_auth_client(self.super_admin)

    def test_list_permissions_returns_200(self):
        resp = self.client.get(f"{BASE}/admin/permissions")
        self.assertEqual(resp.status_code, 200)

    def test_list_permissions_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/permissions")
        self.assertEqual(resp.status_code, 403)


class RoleCRUDTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.client = admin_auth_client(self.super_admin)

    def _create_role(self, name="Content Reviewer"):
        return self.client.post(
            f"{BASE}/admin/roles/create",
            {
                "name": name,
                "description": "Can view content.",
                "permissions": [Permission.CONTENT_VIEW],
            },
            format="json",
        )

    def test_create_role_returns_201(self):
        resp = self._create_role()
        self.assertEqual(resp.status_code, 201)

    def test_list_roles_returns_200(self):
        self._create_role()
        resp = self.client.get(f"{BASE}/admin/roles")
        self.assertEqual(resp.status_code, 200)

    def test_get_role_by_id(self):
        role = Role.objects.create(
            name="Inspector",
            permissions=[Permission.ANALYTICS_VIEW],
        )
        resp = self.client.get(f"{BASE}/admin/roles/{role.id}")
        self.assertEqual(resp.status_code, 200)

    def test_update_role_name(self):
        role = Role.objects.create(name="OldName", permissions=[])
        resp = self.client.patch(
            f"{BASE}/admin/roles/{role.id}/update",
            {"name": "NewName"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        role.refresh_from_db()
        self.assertEqual(role.name, "NewName")

    def test_delete_role_returns_200(self):
        role = Role.objects.create(name="ToDelete", permissions=[])
        resp = self.client.delete(f"{BASE}/admin/roles/{role.id}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Role.objects.filter(id=role.id).exists())

    def test_delete_role_assigned_to_admin_fails(self):
        """Deleting a role currently assigned to an admin user must fail."""
        _, role = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="assignee@skiflux.com",
        )
        resp = self.client.delete(f"{BASE}/admin/roles/{role.id}/delete")
        self.assertEqual(resp.status_code, 400)

    def test_create_role_non_super_admin_is_blocked(self):
        admin, _ = make_admin_with_role(
            [Permission.ROLES_VIEW],
            email="limited@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(
            f"{BASE}/admin/roles/create",
            {"name": "Sneaky Role", "permissions": []},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class AdminUserCRUDTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.client = admin_auth_client(self.super_admin)
        self.role = Role.objects.create(
            name="BasicRole", permissions=[Permission.CONTENT_VIEW]
        )

    def _create_admin(self, email="new@skiflux.com"):
        return self.client.post(
            f"{BASE}/admin/users/create",
            {
                "first_name": "New",
                "last_name": "Admin",
                "email": email,
                "role_type": AdminUser.RoleType.ADMIN,
                "role_id": str(self.role.id),
            },
            format="json",
        )

    def test_create_admin_user_returns_201(self):
        resp = self._create_admin()
        self.assertEqual(resp.status_code, 201)
        created = AdminUser.objects.get(email="new@skiflux.com")
        self.assertTrue(created.must_change_password)
        self.assertTrue(created.is_verified)

    def test_list_admin_users_returns_200(self):
        resp = self.client.get(f"{BASE}/admin/users")
        self.assertEqual(resp.status_code, 200)

    def test_get_admin_user_by_id(self):
        new_admin = AdminUser.objects.create_admin(
            email="fetch@skiflux.com",
            first_name="Fetch",
            password="AdminPass1!",
            roles=[self.role],
        )
        resp = self.client.get(f"{BASE}/admin/users/{new_admin.id}")
        self.assertEqual(resp.status_code, 200)

    def test_update_admin_user_first_name(self):
        new_admin = AdminUser.objects.create_admin(
            email="upd@skiflux.com",
            first_name="Old",
            password="AdminPass1!",
            roles=[self.role],
        )
        resp = self.client.patch(
            f"{BASE}/admin/users/{new_admin.id}/update",
            {"first_name": "Updated"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        new_admin.refresh_from_db()
        self.assertEqual(new_admin.first_name, "Updated")

    def test_deactivate_admin_user(self):
        new_admin = AdminUser.objects.create_admin(
            email="deactivate@skiflux.com",
            first_name="Active",
            password="AdminPass1!",
            roles=[self.role],
        )
        resp = self.client.delete(f"{BASE}/admin/users/{new_admin.id}/deactivate")
        self.assertEqual(resp.status_code, 200)
        new_admin.refresh_from_db()
        self.assertFalse(new_admin.is_active)

    def test_create_admin_non_super_admin_is_blocked(self):
        """Only super admins + ADMIN_USERS_MANAGE can create admin users."""
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="noperm@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.post(
            f"{BASE}/admin/users/create",
            {
                "first_name": "Shadow",
                "email": "shadow@skiflux.com",
                "password": "AdminPass1!",
                "password_confirm": "AdminPass1!",
                "role_type": AdminUser.RoleType.ADMIN,
                "role_id": str(self.role.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class RolesWithMemberCountTests(TestCase):
    """Tests for listing roles with member counts."""

    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.client = admin_auth_client(self.super_admin)

    def test_list_roles_with_member_count_returns_200(self):
        """Test that the endpoint returns 200 for super admin."""
        resp = self.client.get(f"{BASE}/admin/roles/with-member-count")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_list_roles_with_member_count_returns_data(self):
        """Test that the endpoint returns role data with member counts."""
        role1 = Role.objects.create(
            name="Content Reviewer",
            permissions=[Permission.CONTENT_VIEW],
        )
        role2 = Role.objects.create(
            name="Moderator",
            permissions=[Permission.CONTENT_VIEW, Permission.ANALYTICS_VIEW],
        )

        # Create admins and assign roles
        AdminUser.objects.create_admin(
            email="reviewer1@skiflux.com",
            first_name="Reviewer1",
            password="AdminPass1!",
            roles=[role1],
        )
        AdminUser.objects.create_admin(
            email="reviewer2@skiflux.com",
            first_name="Reviewer2",
            password="AdminPass1!",
            roles=[role1],
        )
        AdminUser.objects.create_admin(
            email="mod1@skiflux.com",
            first_name="Mod1",
            password="AdminPass1!",
            roles=[role2],
        )

        resp = self.client.get(f"{BASE}/admin/roles/with-member-count")
        self.assertEqual(resp.status_code, 200)

        roles_data = resp.data["data"]
        roles_dict = {r["name"]: r for r in roles_data}

        # Verify role counts
        self.assertEqual(roles_dict["Content Reviewer"]["total_members"], 2)
        self.assertEqual(roles_dict["Moderator"]["total_members"], 1)

    def test_list_roles_with_member_count_includes_all_fields(self):
        """Test that response includes all required fields."""
        Role.objects.create(
            name="Test Role",
            description="Test Description",
            permissions=[Permission.CONTENT_VIEW],
        )

        resp = self.client.get(f"{BASE}/admin/roles/with-member-count")
        self.assertEqual(resp.status_code, 200)

        roles_data = resp.data["data"]
        test_role = [r for r in roles_data if r["name"] == "Test Role"][0]

        # Verify all expected fields are present
        self.assertIn("id", test_role)
        self.assertIn("name", test_role)
        self.assertIn("description", test_role)
        self.assertIn("permissions", test_role)
        self.assertIn("is_custom", test_role)
        self.assertIn("grants_studio_access", test_role)
        self.assertIn("total_members", test_role)
        self.assertIn("created_at", test_role)

    def test_list_roles_with_member_count_zero_members(self):
        """Test that roles with no members show count as 0."""
        Role.objects.create(
            name="Unused Role",
            permissions=[Permission.ANALYTICS_VIEW],
        )

        resp = self.client.get(f"{BASE}/admin/roles/with-member-count")
        self.assertEqual(resp.status_code, 200)

        roles_data = resp.data["data"]
        unused_role = [r for r in roles_data if r["name"] == "Unused Role"][0]
        self.assertEqual(unused_role["total_members"], 0)

    def test_list_roles_with_member_count_non_super_admin_is_blocked(self):
        """Test that non-super admin users cannot access this endpoint."""
        admin, _ = make_admin_with_role(
            [Permission.ROLES_VIEW],
            email="limited@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/roles/with-member-count")
        self.assertEqual(resp.status_code, 403)

    def test_list_roles_with_member_count_unauthenticated_is_blocked(self):
        """Test that unauthenticated requests are blocked."""
        client = APIClient()
        resp = client.get(f"{BASE}/admin/roles/with-member-count")
        self.assertEqual(resp.status_code, 403)

    def test_list_roles_with_member_count_multiple_admins_one_role(self):
        """Test accurate count when multiple admins have the same role."""
        role = Role.objects.create(
            name="Shared Role",
            permissions=[Permission.CONTENT_VIEW],
        )

        # Create 5 admins with the same role
        for i in range(5):
            AdminUser.objects.create_admin(
                email=f"shared_admin{i}@skiflux.com",
                first_name=f"Admin{i}",
                password="AdminPass1!",
                roles=[role],
            )

        resp = self.client.get(f"{BASE}/admin/roles/with-member-count")
        self.assertEqual(resp.status_code, 200)

        roles_data = resp.data["data"]
        shared_role = [r for r in roles_data if r["name"] == "Shared Role"][0]
        self.assertEqual(shared_role["total_members"], 5)


class LearnerUserListTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.client = admin_auth_client(self.super_admin)

    def _make_learner(self, email, status="active", **kwargs):
        from skiflux.models import User

        return User.objects.create_user(
            email=email,
            first_name="Learner",
            password="StrongPass1!",
            status=status,
            **kwargs,
        )

    def test_list_learners_returns_200(self):
        resp = self.client.get(f"{BASE}/admin/learners")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_list_learners_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/learners")
        self.assertEqual(resp.status_code, 403)

    def test_list_learners_non_super_admin_without_permission_returns_403(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="noperm_learner@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/learners")
        self.assertEqual(resp.status_code, 403)

    def test_list_learners_returns_paginated_structure(self):
        resp = self.client.get(f"{BASE}/admin/learners")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("results", data)

    def test_list_learners_excludes_admin_users(self):
        self._make_learner("learner_only@skiflux.com")
        resp = self.client.get(f"{BASE}/admin/learners")
        emails = [u["email"] for u in resp.data["data"]["results"]]
        self.assertIn("learner_only@skiflux.com", emails)
        self.assertNotIn("superadmin@skiflux.com", emails)

    def test_list_learners_filter_by_status(self):
        self._make_learner("active1@skiflux.com", status="active")
        self._make_learner("suspended1@skiflux.com", status="suspended")
        resp = self.client.get(f"{BASE}/admin/learners?status=suspended")
        results = resp.data["data"]["results"]
        self.assertTrue(all(u["status"] == "suspended" for u in results))

    def test_list_learners_filter_by_skillworld(self):
        self._make_learner("designer@skiflux.com", skillworld="design")
        self._make_learner("coder@skiflux.com", skillworld="code")
        resp = self.client.get(f"{BASE}/admin/learners?skillworld=design")
        results = resp.data["data"]["results"]
        self.assertTrue(all(u["skillworld"] == "design" for u in results))

    def test_list_learners_search_by_email(self):
        self._make_learner("findme@skiflux.com")
        self._make_learner("other@skiflux.com")
        resp = self.client.get(f"{BASE}/admin/learners?search=findme")
        emails = [u["email"] for u in resp.data["data"]["results"]]
        self.assertIn("findme@skiflux.com", emails)
        self.assertNotIn("other@skiflux.com", emails)

    def test_list_learners_search_by_name(self):
        from skiflux.models import User

        User.objects.create_user(
            email="uniquename@skiflux.com",
            first_name="Zephyr",
            password="StrongPass1!",
        )
        resp = self.client.get(f"{BASE}/admin/learners?search=Zephyr")
        results = resp.data["data"]["results"]
        self.assertTrue(len(results) >= 1)
        self.assertTrue(any("Zephyr" in u["first_name"] for u in results))


class LearnerUserStatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.client = admin_auth_client(self.super_admin)

    def _make_learner(self, email, status="active"):
        from skiflux.models import User

        return User.objects.create_user(
            email=email,
            first_name="Learner",
            password="StrongPass1!",
            status=status,
        )

    def test_learner_stats_returns_200(self):
        resp = self.client.get(f"{BASE}/admin/learners/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_learner_stats_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/learners/stats")
        self.assertEqual(resp.status_code, 403)

    def test_learner_stats_non_super_admin_without_permission_returns_403(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="noperm_stats@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/learners/stats")
        self.assertEqual(resp.status_code, 403)

    def test_learner_stats_returns_required_fields(self):
        resp = self.client.get(f"{BASE}/admin/learners/stats")
        data = resp.data["data"]
        for field in [
            "total_users",
            "active_users",
            "suspended_users",
            "deactivated_users",
            "new_this_week",
        ]:
            self.assertIn(field, data)

    def test_learner_stats_counts_are_accurate(self):
        self._make_learner("active1@skiflux.com", status="active")
        self._make_learner("active2@skiflux.com", status="active")
        self._make_learner("suspended1@skiflux.com", status="suspended")
        self._make_learner("deactivated1@skiflux.com", status="deactivated")

        resp = self.client.get(f"{BASE}/admin/learners/stats")
        data = resp.data["data"]

        self.assertEqual(data["total_users"], 4)
        self.assertEqual(data["active_users"], 2)
        self.assertEqual(data["suspended_users"], 1)
        self.assertEqual(data["deactivated_users"], 1)

    def test_learner_stats_new_this_week_accuracy(self):
        # Create one user with an old creation date (outside the window)
        old_user = self._make_learner("olduser@skiflux.com")
        User.objects.filter(id=old_user.id).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        self._make_learner("newuser@skiflux.com")

        resp = self.client.get(f"{BASE}/admin/learners/stats")
        data = resp.data["data"]
        # Only the newly created user should count
        self.assertEqual(data["new_this_week"], 1)

    def test_learner_stats_excludes_admin_users(self):
        resp = self.client.get(f"{BASE}/admin/learners/stats")
        data = resp.data["data"]
        # super admin created in setUp must not be counted
        self.assertEqual(data["total_users"], 0)


class ContentDistributionOverviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.creator = make_creator()
        self.season = make_season(self.creator)
        self.client = admin_auth_client(self.super_admin)

    def _make_episode(self, title="Test Episode", order=1):
        return make_episode(
            self.creator,
            self.season,
            order=order,
            status=Episode.Status.PUBLISHED,
            access_type=Episode.AccessType.FREE,
            title=title,
        )

    def test_content_distribution_returns_200(self):
        resp = self.client.get(f"{BASE}/admin/content/distribution/overview")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

    def test_content_distribution_unauthenticated_returns_403(self):
        client = APIClient()
        resp = client.get(f"{BASE}/admin/content/distribution/overview")
        self.assertEqual(resp.status_code, 403)

    def test_content_distribution_without_content_view_permission_returns_403(self):
        admin, _ = make_admin_with_role(
            [Permission.ANALYTICS_VIEW],
            email="noperm_content@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/distribution/overview")
        self.assertEqual(resp.status_code, 403)

    def test_content_distribution_with_content_view_permission_returns_200(self):
        admin, _ = make_admin_with_role(
            [Permission.CONTENT_VIEW],
            email="hasperm_content@skiflux.com",
        )
        client = admin_auth_client(admin)
        resp = client.get(f"{BASE}/admin/content/distribution/overview")
        self.assertEqual(resp.status_code, 200)

    def test_content_distribution_returns_required_fields(self):
        resp = self.client.get(f"{BASE}/admin/content/distribution/overview")
        data = resp.data["data"]
        self.assertIn("episode_count", data)
        self.assertIn("project_based_task_count", data)
        self.assertIn("assessment_based_task_count", data)

    def test_content_distribution_counts_are_accurate(self):
        from skiflux.models import EpisodeTask

        ep1 = self._make_episode("Episode One", order=1)
        ep2 = self._make_episode("Episode Two", order=2)

        EpisodeTask.objects.create(episode=ep1, kind=EpisodeTask.Kind.PROJECT_BASED)
        EpisodeTask.objects.create(episode=ep1, kind=EpisodeTask.Kind.PROJECT_BASED)
        EpisodeTask.objects.create(episode=ep2, kind=EpisodeTask.Kind.ASSESSMENT)

        resp = self.client.get(f"{BASE}/admin/content/distribution/overview")
        data = resp.data["data"]

        self.assertEqual(data["episode_count"], 2)
        self.assertEqual(data["project_based_task_count"], 2)
        self.assertEqual(data["assessment_based_task_count"], 1)

    def test_content_distribution_empty_db_returns_zeros(self):
        resp = self.client.get(f"{BASE}/admin/content/distribution/overview")
        data = resp.data["data"]

        self.assertEqual(data["episode_count"], 0)
        self.assertEqual(data["project_based_task_count"], 0)
        self.assertEqual(data["assessment_based_task_count"], 0)

    def test_content_distribution_task_kinds_are_counted_independently(self):
        """PROJECT_BASED and ASSESSMENT counts must not bleed into each other."""
        from skiflux.models import EpisodeTask

        ep = self._make_episode("Mixed Episode", order=1)
        for _ in range(3):
            EpisodeTask.objects.create(episode=ep, kind=EpisodeTask.Kind.PROJECT_BASED)
        for _ in range(2):
            EpisodeTask.objects.create(episode=ep, kind=EpisodeTask.Kind.ASSESSMENT)

        resp = self.client.get(f"{BASE}/admin/content/distribution/overview")
        data = resp.data["data"]

        self.assertEqual(data["project_based_task_count"], 3)
        self.assertEqual(data["assessment_based_task_count"], 2)
