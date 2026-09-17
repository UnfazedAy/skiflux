from rest_framework.throttling import AnonRateThrottle


class ForgotPasswordRateThrottle(AnonRateThrottle):
    scope = "forgot_password"


class OTPResendRateThrottle(AnonRateThrottle):
    scope = "otp_resend"


class AdminLoginRateThrottle(AnonRateThrottle):
    scope = "admin_login"


class InvestorSubmitRateThrottle(AnonRateThrottle):
    scope = "investor_submit"
