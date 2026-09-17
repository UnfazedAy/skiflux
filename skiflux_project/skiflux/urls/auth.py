from django.urls import path

from skiflux.views import (
    apple_auth_callback,
    apple_auth_init,
    apple_social_mobile_login,
    complete_onboarding,
    facebook_social_mobile_login,
    forgot_password,
    google_auth_callback,
    google_auth_init,
    google_social_mobile_login,
    health_check,
    login,
    logout,
    resend_otp,
    reset_password,
    signup,
    token_refresh,
    verify_email,
    verify_password_otp,
    change_password,
)

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("auth/signup", signup, name="auth-signup"),
    path("auth/login", login, name="auth-login"),
    path("auth/forgot-password", forgot_password, name="auth-forgot-password"),
    path("auth/reset-password", reset_password, name="auth-reset-password"),
    path(
        "auth/verify-register-email",
        verify_email,
        name="auth-verify-register-email",
    ),
    path("auth/token/refresh", token_refresh, name="auth-token-refresh"),
    path(
        "auth/verify-forgot-password-otp",
        verify_password_otp,
        name="auth-verify-forgot-password-otp",
    ),
    path(
        "auth/resend-register-otp",
        resend_otp,
        name="auth-resend-register-otp",
    ),
    path("auth/logout", logout, name="auth-logout"),
    path("auth/change-password", change_password, name="auth-change-password"),
    path("auth/social/google/init", google_auth_init, name="auth-google-init"),
    path(
        "auth/social/google/callback",
        google_auth_callback,
        name="auth-google-callback",
    ),
    path("auth/social/apple/init", apple_auth_init, name="auth-apple-init"),
    path(
        "auth/social/apple/callback",
        apple_auth_callback,
        name="auth-apple-callback",
    ),
    path(
        "auth/social/mobile/google",
        google_social_mobile_login,
        name="auth-google",
    ),
    path(
        "auth/social/mobile/facebook",
        facebook_social_mobile_login,
        name="auth-facebook",
    ),
    path(
        "auth/social/mobile/apple",
        apple_social_mobile_login,
        name="auth-apple",
    ),
    path(
        "profile/complete-onboarding/",
        complete_onboarding,
        name="complete-onboarding",
    ),
]
