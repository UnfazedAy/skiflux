import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from skiflux.models.platform_settings import SystemSecurityConfig

logger = logging.getLogger(__name__)

LOCKOUT_CACHE_PREFIX = "login_lockout"


def get_lockout_config():
    cfg = SystemSecurityConfig.get_config()
    return cfg.max_failed_login_attempts, cfg.account_lockout_duration_minutes


def _cache_key(identifier: str) -> str:
    return f"{LOCKOUT_CACHE_PREFIX}:{identifier.lower()}"


def is_account_locked(identifier) -> bool:
    email = identifier.email if hasattr(identifier, "email") else str(identifier)
    # 1. Fast path: cache
    data = cache.get(_cache_key(email))
    if data:
        locked_until = data.get("locked_until")
        if locked_until and locked_until > timezone.now():
            return True
    # 2. Fallback: DB (survives Redis restart)
    if hasattr(identifier, "locked_until") and identifier.locked_until:
        return identifier.locked_until > timezone.now()
    return False


def record_failed_login(identifier) -> None:
    email = identifier.email if hasattr(identifier, "email") else str(identifier)
    max_attempts, duration = get_lockout_config()
    key = _cache_key(email)
    data = cache.get(key, {"count": 0})
    data["count"] += 1
    data["last_failed"] = timezone.now()

    if data["count"] >= max_attempts:
        locked_until = timezone.now() + timedelta(minutes=duration)
        data["locked_until"] = locked_until
        logger.warning(
            "Account locked after %d failed attempts: %s", data["count"], email
        )
        if hasattr(identifier, "locked_until"):
            type(identifier).objects.filter(pk=identifier.pk).update(
                failed_login_attempts=data["count"],
                last_failed_login=data["last_failed"],
                locked_until=locked_until,
            )
    cache.set(key, data, timeout=86400)


def manually_unlock_account(identifier) -> None:
    """Admin-initiated force unlock. Clears both cache and DB lockout state."""
    email = identifier.email if hasattr(identifier, "email") else str(identifier)
    logger.info("Account manually unlocked by admin action: %s", email)
    reset_failed_login_attempts(identifier)


def reset_failed_login_attempts(identifier) -> None:
    email = identifier.email if hasattr(identifier, "email") else str(identifier)
    logger.info("Login attempt counter reset for: %s", email)
    cache.delete(_cache_key(email))
    if hasattr(identifier, "locked_until"):
        type(identifier).objects.filter(pk=identifier.pk).update(
            failed_login_attempts=0,
            last_failed_login=None,
            locked_until=None,
        )
