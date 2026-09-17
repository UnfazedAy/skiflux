import base64

import jwt
import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from django.conf import settings
from django.core.cache import cache
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

_APPLE_JWKS_CACHE_KEY = "apple_jwks_keys"
_APPLE_JWKS_TTL = 3600


def _get_apple_jwks() -> list:
    cached = cache.get(_APPLE_JWKS_CACHE_KEY)
    if cached is not None:
        return cached
    resp = requests.get("https://appleid.apple.com/auth/keys", timeout=5)
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    cache.set(_APPLE_JWKS_CACHE_KEY, keys, timeout=_APPLE_JWKS_TTL)
    return keys


def verify_google_token(token: str) -> dict:
    try:
        request = google_requests.Request()
        id_info = id_token.verify_oauth2_token(
            token,
            request,
            settings.GOOGLE_CLIENT_ID,
        )
        return {
            "social_id": id_info["sub"],
            "email": id_info["email"],
            "first_name": id_info.get("given_name", ""),
            "last_name": id_info.get("family_name", ""),
            "avatar_url": id_info.get("picture", None),
        }
    except (GoogleAuthError, ValueError):
        raise ValueError("Invalid or expired Google token.")
    except Exception:
        raise ValueError("Could not verify Google token. Please try again.")


def verify_facebook_token(access_token: str) -> dict:
    app_token = f"{settings.FACEBOOK_APP_ID}|{settings.FACEBOOK_APP_SECRET}"

    debug_resp = requests.get(
        "https://graph.facebook.com/debug_token",
        params={"input_token": access_token, "access_token": app_token},
        timeout=5,
    )
    debug_data = debug_resp.json().get("data", {})
    if not debug_data.get("is_valid"):
        raise ValueError("Invalid or expired Facebook token.")
    if str(debug_data.get("app_id")) != str(settings.FACEBOOK_APP_ID):
        raise ValueError("Facebook token does not belong to this app.")

    profile_resp = requests.get(
        "https://graph.facebook.com/me",
        params={
            "fields": "id,email,first_name,last_name,picture.type(large)",
            "access_token": access_token,
        },
        timeout=5,
    )
    profile = profile_resp.json()
    if "error" in profile:
        raise ValueError("Could not fetch Facebook user profile.")

    return {
        "social_id": profile["id"],
        "email": profile.get("email"),
        "first_name": profile.get("first_name", ""),
        "last_name": profile.get("last_name", ""),
        "avatar_url": profile.get("picture", {}).get("data", {}).get("url"),
    }


def _base64url_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _get_apple_public_key(kid: str):
    keys = _get_apple_jwks()
    for key_data in keys:
        if key_data["kid"] == kid:
            n = int.from_bytes(_base64url_decode(key_data["n"]), "big")
            e = int.from_bytes(_base64url_decode(key_data["e"]), "big")
            public_numbers = RSAPublicNumbers(e=e, n=n)
            return public_numbers.public_key(default_backend())
    cache.delete(_APPLE_JWKS_CACHE_KEY)
    keys = _get_apple_jwks()
    for key_data in keys:
        if key_data["kid"] == kid:
            n = int.from_bytes(_base64url_decode(key_data["n"]), "big")
            e = int.from_bytes(_base64url_decode(key_data["e"]), "big")
            public_numbers = RSAPublicNumbers(e=e, n=n)
            return public_numbers.public_key(default_backend())
    raise ValueError("Apple public key not found.")


def verify_apple_token(
    identity_token: str, first_name: str = "", last_name: str = ""
) -> dict:
    try:
        header = jwt.get_unverified_header(identity_token)
        public_key = _get_apple_public_key(header["kid"])

        payload = jwt.decode(
            identity_token,
            public_key,
            algorithms=["RS256"],
            audience=settings.APPLE_CLIENT_ID,
            issuer="https://appleid.apple.com",
        )

        return {
            "social_id": payload["sub"],
            "email": payload.get("email"),
            "first_name": first_name,
            "last_name": last_name,
            "avatar_url": None,
        }
    except jwt.ExpiredSignatureError:
        raise ValueError("Apple token has expired.")
    except Exception:
        raise ValueError("Invalid Apple token.")
