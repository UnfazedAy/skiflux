"""
User Authentication Tests
Covers: signup, email verification, login, logout,
        token refresh, forgot/reset password, resend OTP.
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from skiflux.models import User
from skiflux.utils.auth import (
    create_refresh_token,
    set_email_verification_otp,
    set_password_reset_otp,
)

from .conftest import make_verified_user, user_auth_client

BASE = "/api/v1"


class HealthCheckTest(TestCase):
    def test_health_check_returns_200(self):
        client = APIClient()
        resp = client.get(f"{BASE}/health/")
        self.assertEqual(resp.status_code, 200)


class SignupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.email_patcher = patch("skiflux.tasks.auth.requests.post")
        mock_post = self.email_patcher.start()
        mock_post.return_value = MagicMock(
            status_code=201, raise_for_status=lambda: None
        )

    def tearDown(self):
        self.email_patcher.stop()

    def _signup(self, payload=None):
        client = APIClient()
        payload = payload or {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "password": "StrongPass1!",
            "password_confirm": "StrongPass1!",
        }
        return client.post(f"{BASE}/auth/signup", payload)

    def test_signup_success_returns_201(self):
        resp = self._signup()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(User.objects.filter(email="test@example.com").exists())

    def test_signup_user_is_unverified_by_default(self):
        self._signup()
        user = User.objects.get(email="test@example.com")
        self.assertFalse(user.is_verified)

    def test_signup_missing_email_returns_400(self):
        resp = self._signup(
            {
                "first_name": "A",
                "password": "StrongPass1!",
                "password_confirm": "StrongPass1!",
            }
        )
        self.assertEqual(resp.status_code, 400)

    def test_signup_weak_password_returns_400(self):
        resp = self._signup(
            {
                "first_name": "A",
                "email": "weak@example.com",
                "password": "weakpass",
                "password_confirm": "weakpass",
            }
        )
        self.assertEqual(resp.status_code, 400)

    def test_signup_password_mismatch_returns_400(self):
        resp = self._signup(
            {
                "first_name": "A",
                "email": "pw@example.com",
                "password": "StrongPass1!",
                "password_confirm": "Different1!",
            }
        )
        self.assertEqual(resp.status_code, 400)

    def test_signup_duplicate_email_returns_400(self):
        make_verified_user(email="dup@example.com")
        resp = self._signup(
            {
                "first_name": "B",
                "email": "dup@example.com",
                "password": "StrongPass1!",
                "password_confirm": "StrongPass1!",
            }
        )
        self.assertEqual(resp.status_code, 400)


class EmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.email_patcher = patch("skiflux.tasks.auth.requests.post")
        mock_post = self.email_patcher.start()
        mock_post.return_value = MagicMock(
            status_code=201, raise_for_status=lambda: None
        )

    def tearDown(self):
        self.email_patcher.stop()

    def test_verify_email_with_correct_otp(self):
        user = User.objects.create_user(
            email="verify@example.com",
            first_name="V",
            password="StrongPass1!",
        )
        set_email_verification_otp(user.email, "123456")
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/verify-register-email",
            {"email": user.email, "otp": "123456"},
        )
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_verify_email_with_wrong_otp_returns_400(self):
        user = User.objects.create_user(
            email="wrong@example.com",
            first_name="W",
            password="StrongPass1!",
        )
        set_email_verification_otp(user.email, "999999")
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/verify-register-email",
            {"email": user.email, "otp": "000000"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_resend_otp_success(self):
        user = User.objects.create_user(
            email="resend@example.com",
            first_name="R",
            password="StrongPass1!",
        )
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/resend-register-otp",
            {"email": user.email},
        )
        self.assertEqual(resp.status_code, 200)


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="login@example.com")

    def test_login_success_returns_tokens(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/login",
            {"email": "login@example.com", "password": "StrongPass1!"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.data["data"])
        self.assertIn("refresh_token", resp.data["data"])

    def test_login_wrong_password_returns_400(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/login",
            {"email": "login@example.com", "password": "WrongPass1!"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_login_unverified_user_is_blocked(self):
        User.objects.create_user(
            email="unverified@example.com",
            first_name="U",
            password="StrongPass1!",
            is_verified=False,
        )
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/login",
            {
                "email": "unverified@example.com",
                "password": "StrongPass1!",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_login_nonexistent_email_returns_400(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/login",
            {"email": "ghost@example.com", "password": "StrongPass1!"},
        )
        self.assertEqual(resp.status_code, 400)


class TokenRefreshTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="refresh@example.com")

    def test_token_refresh_returns_new_tokens(self):
        refresh = create_refresh_token(str(self.user.id))
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/token/refresh",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.data["data"])

    def test_token_refresh_with_invalid_token_returns_401(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/token/refresh",
            {"refresh_token": "not-a-real-token"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_refresh_token_can_only_be_used_once(self):
        """After first refresh, the old refresh token must be blacklisted."""
        refresh = create_refresh_token(str(self.user.id))
        client = APIClient()
        resp1 = client.post(
            f"{BASE}/auth/token/refresh",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp1.status_code, 200)
        resp2 = client.post(
            f"{BASE}/auth/token/refresh",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp2.status_code, 401)


class LogoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="logout@example.com")

    def test_logout_success(self):
        refresh = create_refresh_token(str(self.user.id))
        client = user_auth_client(self.user)
        resp = client.post(
            f"{BASE}/auth/logout",
            {"refresh_token": refresh},
        )
        self.assertEqual(resp.status_code, 200)

    def test_logout_requires_authentication(self):
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/logout",
            {"refresh_token": "anything"},
        )
        self.assertEqual(resp.status_code, 403)


class ForgotPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="forgot@example.com")

    def test_forgot_password_always_returns_200(self):
        """Security: must not leak whether email exists."""
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/forgot-password",
            {"email": "nonexistent@example.com"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_verify_password_otp_success(self):
        set_password_reset_otp(self.user.email, "654321")
        client = APIClient()
        resp = client.post(
            f"{BASE}/auth/verify-forgot-password-otp",
            {"email": self.user.email, "otp": "654321"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_reset_password_success(self):
        set_password_reset_otp(self.user.email, "111111")
        client = APIClient()
        client.post(
            f"{BASE}/auth/verify-forgot-password-otp",
            {"email": self.user.email, "otp": "111111"},
        )
        resp = client.post(
            f"{BASE}/auth/reset-password",
            {
                "email": self.user.email,
                "otp": "111111",
                "new_password": "NewStrongPass1!",
                "confirm_new_password": "NewStrongPass1!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPass1!"))


class JWTScopeIsolationTests(TestCase):
    """Admin tokens must NOT be accepted on user endpoints and vice versa."""

    def setUp(self):
        cache.clear()
        from .conftest import make_super_admin

        self.admin = make_super_admin()

    def test_admin_token_rejected_on_user_endpoint(self):
        from skiflux.utils.auth import create_admin_access_token

        token = create_admin_access_token(str(self.admin.id))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = client.post(f"{BASE}/profile/complete-onboarding/", {})
        self.assertEqual(resp.status_code, 403)


class OTPRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_otp_rate_limit_enforced_after_five_attempts(self):
        from skiflux.utils.auth import (
            set_email_verification_otp,
            verify_email_otp,
        )

        set_email_verification_otp("ratelimit@example.com", "123456")
        for _ in range(5):
            try:
                verify_email_otp("ratelimit@example.com", "000000")
            except ValueError:
                pass
        with self.assertRaises(ValueError):
            verify_email_otp("ratelimit@example.com", "123456")

    def test_otp_consumed_after_correct_entry(self):
        from skiflux.utils.auth import (
            set_email_verification_otp,
            verify_email_otp,
        )

        set_email_verification_otp("consume@example.com", "654321")
        self.assertTrue(verify_email_otp("consume@example.com", "654321"))
        self.assertFalse(verify_email_otp("consume@example.com", "654321"))


class ChangePasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="changepass@example.com")
        self.client = user_auth_client(self.user)

    def test_change_password_unauthenticated_returns_403(self):
        anon_client = APIClient()
        resp = anon_client.post(
            f"{BASE}/auth/change-password",
            {
                "current_password": "StrongPass1!",
                "new_password": "NewStrongPass1!",
                "confirm_new_password": "NewStrongPass1!",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_change_password_wrong_current_password_returns_400(self):
        resp = self.client.post(
            f"{BASE}/auth/change-password",
            {
                "current_password": "WrongPassword1!",
                "new_password": "NewStrongPass1!",
                "confirm_new_password": "NewStrongPass1!",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("current_password", resp.data["message"])

    def test_change_password_mismatched_new_passwords_returns_400(self):
        resp = self.client.post(
            f"{BASE}/auth/change-password",
            {
                "current_password": "StrongPass1!",
                "new_password": "NewStrongPass1!",
                "confirm_new_password": "DifferentPass1!",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("confirm_new_password", resp.data["message"])

    def test_change_password_same_password_returns_400(self):
        resp = self.client.post(
            f"{BASE}/auth/change-password",
            {
                "current_password": "StrongPass1!",
                "new_password": "StrongPass1!",
                "confirm_new_password": "StrongPass1!",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("new_password", resp.data["message"])

    def test_change_password_weak_password_returns_400(self):
        resp = self.client.post(
            f"{BASE}/auth/change-password",
            {
                "current_password": "StrongPass1!",
                "new_password": "weak",
                "confirm_new_password": "weak",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_change_password_success(self):
        resp = self.client.post(
            f"{BASE}/auth/change-password",
            {
                "current_password": "StrongPass1!",
                "new_password": "NewStrongPass1!",
                "confirm_new_password": "NewStrongPass1!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "success")

        # Refresh user and check password
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPass1!"))

        # Verify can login with the new password
        anon_client = APIClient()
        login_resp = anon_client.post(
            f"{BASE}/auth/login",
            {"email": "changepass@example.com", "password": "NewStrongPass1!"},
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn("access_token", login_resp.data["data"])
