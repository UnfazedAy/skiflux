"""
Extended admin RBAC tests: multi-role assignment, delegated admin create,
repository status transitions.
"""

from django.core.cache import cache
from django.test import TestCase

from skiflux.models import AdminUser
from skiflux.models.role import Permission, Role
from skiflux.repositories.admin_user_repository import AdminUserRepository

from .conftest import admin_auth_client, make_admin_with_role, make_super_admin

BASE = "/api/v1"


class DelegatedAdminCreateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.role = Role.objects.create(
            name="UserManager",
            permissions=[
                Permission.ADMIN_USERS_VIEW,
                Permission.ADMIN_USERS_MANAGE,
            ],
        )
        self.manager, _ = make_admin_with_role(
            self.role.permissions,
            email="manager@skiflux.com",
        )
        self.client = admin_auth_client(self.manager)

    def test_admin_with_manage_permission_can_create_admin(self):
        resp = self.client.post(
            f"{BASE}/admin/users/create",
            {
                "first_name": "Delegated",
                "last_name": "Admin",
                "email": "delegated@skiflux.com",
                "role_type": AdminUser.RoleType.ADMIN,
                "role_id": str(self.role.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        created = AdminUser.objects.get(email="delegated@skiflux.com")
        self.assertEqual(created.role_type, AdminUser.RoleType.ADMIN)
        self.assertEqual(created.created_by_id, self.manager.id)
        self.assertEqual(created.roles.count(), 1)
        self.assertEqual(created.roles.first().id, self.role.id)
        self.assertTrue(created.must_change_password)
        self.assertTrue(created.is_verified)


class MultiRoleAssignmentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = make_super_admin()
        self.client = admin_auth_client(self.super_admin)
        self.portal_role = Role.objects.create(
            name="PortalOps",
            permissions=[Permission.CONTENT_VIEW, Permission.ECONOMY_VIEW],
        )
        self.platform_admin = AdminUser.objects.create_admin(
            email="platform@skiflux.com",
            first_name="Platform",
            password="AdminPass1!",
            role_type=AdminUser.RoleType.ADMIN,
            roles=[self.portal_role],
        )
        self.creator_studio_role = Role.get_or_create_creator_studio_role()

    def test_existing_admin_can_gain_creator_role_type(self):
        resp = self.client.post(
            f"{BASE}/admin/users/{self.platform_admin.id}/roles/assign",
            {"add_role_types": [AdminUser.RoleType.CREATOR]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.platform_admin.refresh_from_db()
        self.assertEqual(self.platform_admin.role_type, AdminUser.RoleType.ADMIN)
        self.assertTrue(self.platform_admin.has_role_type(AdminUser.RoleType.CREATOR))
        self.assertTrue(self.platform_admin.can_use_studio)
        self.assertEqual(self.platform_admin.roles.count(), 1)
        self.assertTrue(
            self.platform_admin.roles.filter(id=self.portal_role.id).exists()
        )
        self.assertTrue(self.platform_admin.has_permission(Permission.CONTENT_VIEW))

    def test_admin_with_roles_manage_can_grant_creator_role_type(self):
        roles_manager_role = Role.objects.create(
            name="RolesManager",
            permissions=[Permission.ROLES_MANAGE],
        )
        manager, _ = make_admin_with_role(
            roles_manager_role.permissions,
            email="rolesmgr@skiflux.com",
        )
        client = admin_auth_client(manager)
        resp = client.post(
            f"{BASE}/admin/users/{self.platform_admin.id}/roles/assign",
            {"add_role_types": [AdminUser.RoleType.CREATOR]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.platform_admin.refresh_from_db()
        self.assertTrue(self.platform_admin.has_role_type(AdminUser.RoleType.CREATOR))

    def test_existing_creator_can_gain_custom_portal_role(self):
        creator = AdminUser.objects.create_admin(
            email="videocreator@skiflux.com",
            first_name="Video",
            password="CreatorPass1!",
            role_type=AdminUser.RoleType.CREATOR,
            role_types=[AdminUser.RoleType.CREATOR],
            is_verified=True,
        )
        custom = Role.objects.create(
            name="CreatorModerator",
            permissions=[Permission.CREATOR_VIEW, Permission.CREATOR_MANAGE],
        )
        resp = self.client.post(
            f"{BASE}/admin/users/{creator.id}/roles/assign",
            {"add_role_ids": [str(custom.id)]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        creator.refresh_from_db()
        self.assertEqual(creator.role_type, AdminUser.RoleType.CREATOR)
        self.assertTrue(creator.can_use_studio)
        self.assertTrue(creator.has_permission(Permission.CREATOR_MANAGE))
        self.assertEqual(creator.roles.count(), 1)

    def test_cannot_remove_last_portal_role_from_admin(self):
        admin = AdminUser.objects.create_admin(
            email="lonely@skiflux.com",
            first_name="Lonely",
            password="AdminPass1!",
            role_type=AdminUser.RoleType.ADMIN,
            roles=[self.portal_role],
        )
        resp = self.client.post(
            f"{BASE}/admin/users/{admin.id}/roles/assign",
            {"remove_role_ids": [str(self.portal_role.id)]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class AdminRepositoryStatusTests(TestCase):
    def setUp(self):
        self.repo = AdminUserRepository()
        self.admin = make_admin_with_role([Permission.CONTENT_VIEW])[0]

    def test_deactivate_sets_status_and_inactive(self):
        self.repo.deactivate(self.admin)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.status, AdminUser.Status.DEACTIVATED)
        self.assertFalse(self.admin.is_active)

    def test_suspend_sets_status(self):
        self.repo.suspend(self.admin)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.status, AdminUser.Status.SUSPENDED)
        self.assertFalse(self.admin.is_active)

    def test_reactivate_sets_active_status(self):
        self.repo.deactivate(self.admin)
        self.repo.reactivate(self.admin)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.status, AdminUser.Status.ACTIVE)
        self.assertTrue(self.admin.is_active)
