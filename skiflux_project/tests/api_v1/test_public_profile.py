import uuid

from django.core.cache import cache
from django.test import TestCase

from skiflux.models.gamification import Badge, UserBadge
from skiflux.models.user import User

from .conftest import make_verified_user, user_auth_client

BASE = "/api/v1"


class PublicUserProfileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.viewer = make_verified_user(email="viewer@example.com")
        self.target = make_verified_user(
            email="target@example.com",
            username="targetuser",
            first_name="Target",
            last_name="User",
            bio="Hello world",
            xp=1200,
            current_level="amateur",
        )
        self.client = user_auth_client(self.viewer)

    def test_get_public_profile_by_id(self):
        resp = self.client.get(f"{BASE}/users/{self.target.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["username"], "targetuser")
        self.assertEqual(data["xp"], 1200)
        self.assertEqual(data["current_level"], "amateur")
        self.assertNotIn("email", data)
        for field in [
            "id",
            "first_name",
            "last_name",
            "avatar_url",
            "bio",
            "rank",
            "task_done",
            "skillworld",
            "earned_badges",
        ]:
            self.assertIn(field, data)

    def test_get_public_profile_by_username(self):
        resp = self.client.get(f"{BASE}/users/by-username/targetuser")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["data"]["id"], str(self.target.id))

    def test_deactivated_user_returns_404(self):
        self.target.status = User.Status.DEACTIVATED
        self.target.save(update_fields=["status"])
        resp = self.client.get(f"{BASE}/users/{self.target.id}")
        self.assertEqual(resp.status_code, 404)

    def test_suspended_user_returns_404(self):
        self.target.status = User.Status.SUSPENDED
        self.target.save(update_fields=["status"])
        resp = self.client.get(f"{BASE}/users/{self.target.id}")
        self.assertEqual(resp.status_code, 404)

    def test_unknown_user_returns_404(self):
        resp = self.client.get(f"{BASE}/users/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)

    def test_public_profile_includes_earned_badges(self):
        badge = Badge.objects.create(
            name="Early Bird",
            description="Joined early",
            icon_public_id="badges/early-bird",
        )
        UserBadge.objects.create(user=self.target, badge=badge)
        resp = self.client.get(f"{BASE}/users/{self.target.id}")
        self.assertEqual(resp.status_code, 200)
        badges = resp.data["data"]["earned_badges"]
        self.assertEqual(len(badges), 1)
        self.assertEqual(badges[0]["badge"]["name"], "Early Bird")
        self.assertIsNotNone(badges[0]["badge"]["icon_url"])
