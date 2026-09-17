"""
Shared fixtures for all api_v1 tests.

All database-touching tests use Django's TestCase transaction rollback,
so each test starts with a clean state. Cache is cleared in setUp hooks
inside each TestCase, not here, because fixtures run at the module level.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIClient

from skiflux.models import AdminUser, User
from skiflux.models.content import Episode, Season
from skiflux.models.role import Role
from skiflux.utils.auth import (
    create_access_token,
    create_admin_access_token,
)


@pytest.fixture(autouse=True)
def mock_brevo_email():
    """Prevent real HTTP calls to Brevo in all tests."""
    with patch("skiflux.tasks.auth.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=201, raise_for_status=lambda: None
        )
        yield mock_post


def make_verified_user(
    email="user@example.com",
    first_name="Test",
    password="StrongPass1!",
    **kwargs,
):
    user = User.objects.create_user(
        email=email,
        first_name=first_name,
        password=password,
        is_verified=True,
        **kwargs,
    )
    return user


def make_super_admin(
    email="superadmin@skiflux.com",
    first_name="Super",
    password="AdminPass1!",
):
    return AdminUser.objects.create_super_admin(
        email=email,
        first_name=first_name,
        password=password,
    )


def make_admin(
    email="admin@skiflux.com",
    first_name="Admin",
    password="AdminPass1!",
):
    """Create a basic admin user without specific roles."""
    return AdminUser.objects.create_admin(
        email=email,
        first_name=first_name,
        password=password,
    )


def make_admin_with_role(permissions: list, email="admin@skiflux.com"):
    role = Role.objects.create(
        name=f"Role-{uuid.uuid4().hex[:6]}",
        permissions=permissions,
    )
    admin = AdminUser.objects.create_admin(
        email=email,
        first_name="Admin",
        password="AdminPass1!",
        roles=[role],
    )
    return admin, role


def make_creator(
    email="creator@skiflux.com",
    username="testcreator",
    password="CreatorPass1!",
    bio="A test creator",
    avatar_public_id="avatar/test1234",
):
    creator = AdminUser.objects.create_admin(
        email=email,
        first_name="Creator",
        password=password,
        bio=bio,
        avatar_public_id=avatar_public_id,
        role_type=AdminUser.RoleType.CREATOR,
        role_types=[AdminUser.RoleType.CREATOR],
        username=username,
        is_verified=True,
    )
    return creator


def make_season(creator, title="Season One", skillworld="design"):
    return Season.objects.create(
        creator=creator,
        title=title,
        description="A great season",
        skillworld=skillworld,
    )


def make_episode(
    creator,
    season,
    title="Episode One",
    order=1,
    status=Episode.Status.PUBLISHED,
    access_type=Episode.AccessType.FREE,
):
    return Episode.objects.create(
        creator=creator,
        season=season,
        title=title,
        description="Great content",
        order=order,
        status=status,
        access_type=access_type,
    )


def user_auth_client(user):
    client = APIClient()
    token = create_access_token(str(user.id))
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def admin_auth_client(admin):
    client = APIClient()
    token = create_admin_access_token(str(admin.id))
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def anon_client():
    return APIClient()
