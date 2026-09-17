"""
Model & Permissions Unit Tests
Covers: Role.has_permission, AdminUser.has_permission,
        AdminUser.get_all_permissions, AdminUser.is_super_admin,
        Permission constants.
"""

from django.test import TestCase

from skiflux.models import AdminUser
from skiflux.models.role import Permission, Role


class RoleModelTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(
            name="Test Role",
            permissions=[Permission.CONTENT_VIEW, Permission.ANALYTICS_VIEW],
        )

    def test_has_permission_returns_true_for_granted(self):
        self.assertTrue(self.role.has_permission(Permission.CONTENT_VIEW))

    def test_has_permission_returns_false_for_not_granted(self):
        self.assertFalse(self.role.has_permission(Permission.CONTENT_MANAGE))

    def test_has_permission_returns_false_for_empty_role(self):
        empty_role = Role.objects.create(name="Empty Role", permissions=[])
        self.assertFalse(empty_role.has_permission(Permission.CONTENT_VIEW))

    def test_role_str_returns_name(self):
        self.assertEqual(str(self.role), "Test Role")


class AdminUserModelTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(
            name="Limited",
            permissions=[Permission.CREATOR_VIEW],
        )
        self.super_admin = AdminUser.objects.create_super_admin(
            email="super@test.com",
            first_name="Super",
            password="AdminPass1!",
        )
        self.limited_admin = AdminUser.objects.create_admin(
            email="limited@test.com",
            first_name="Limited",
            password="AdminPass1!",
            roles=[self.role],
        )
        self.roleless_admin = AdminUser.objects.create_admin(
            email="roleless@test.com",
            first_name="Roleless",
            password="AdminPass1!",
        )

    def test_super_admin_is_super_admin_returns_true(self):
        self.assertTrue(self.super_admin.is_super_admin)

    def test_regular_admin_is_not_super_admin(self):
        self.assertFalse(self.limited_admin.is_super_admin)

    def test_super_admin_has_all_permissions(self):
        for perm in Permission.ALL:
            self.assertTrue(self.super_admin.has_permission(perm))

    def test_limited_admin_has_only_assigned_permissions(self):
        self.assertTrue(self.limited_admin.has_permission(Permission.CREATOR_VIEW))
        self.assertFalse(self.limited_admin.has_permission(Permission.CREATOR_MANAGE))

    def test_roleless_admin_has_no_permissions(self):
        self.assertFalse(self.roleless_admin.has_permission(Permission.CONTENT_VIEW))

    def test_super_admin_get_all_permissions_returns_all(self):
        perms = self.super_admin.get_all_permissions()
        for perm in Permission.ALL:
            self.assertIn(perm, perms)

    def test_limited_admin_get_all_permissions_returns_subset(self):
        perms = self.limited_admin.get_all_permissions()
        self.assertIn(Permission.CREATOR_VIEW, perms)
        self.assertNotIn(Permission.CREATOR_MANAGE, perms)

    def test_admin_is_authenticated_property(self):
        self.assertTrue(self.limited_admin.is_authenticated)

    def test_admin_is_anonymous_property(self):
        self.assertFalse(self.limited_admin.is_anonymous)

    def test_admin_check_password(self):
        self.assertTrue(self.super_admin.check_password("AdminPass1!"))
        self.assertFalse(self.super_admin.check_password("WrongPassword!"))

    def test_platform_admin_can_hold_admin_and_creator_role_types(self):
        admin = AdminUser.objects.create_admin(
            email="dual@skiflux.com",
            first_name="Dual",
            password="AdminPass1!",
            role_type=AdminUser.RoleType.ADMIN,
            role_types=[AdminUser.RoleType.ADMIN, AdminUser.RoleType.CREATOR],
            roles=[self.role],
        )
        self.assertEqual(admin.role_type, AdminUser.RoleType.ADMIN)
        self.assertTrue(admin.has_role_type(AdminUser.RoleType.CREATOR))
        self.assertTrue(admin.can_use_studio)
        self.assertFalse(admin.is_super_admin)

    def test_limited_admin_permissions_union_from_roles(self):
        extra = Role.objects.create(
            name="ExtraPerms",
            permissions=[Permission.ECONOMY_VIEW],
        )
        self.limited_admin.roles.add(extra)
        self.assertTrue(self.limited_admin.has_permission(Permission.ECONOMY_VIEW))

    def test_super_admin_has_empty_roles_assignment(self):
        self.assertEqual(self.super_admin.roles.count(), 0)


class PermissionConstantsTests(TestCase):
    def test_all_permissions_are_unique(self):
        """No duplicate permission codenames."""
        self.assertEqual(len(Permission.ALL), len(set(Permission.ALL)))

    def test_creator_view_and_manage_exist(self):
        self.assertIn(Permission.CREATOR_VIEW, Permission.ALL)
        self.assertIn(Permission.CREATOR_MANAGE, Permission.ALL)

    def test_admin_users_manage_exists(self):
        self.assertIn(Permission.ADMIN_USERS_MANAGE, Permission.ALL)
