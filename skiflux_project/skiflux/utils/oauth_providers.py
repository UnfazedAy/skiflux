import time

import httpx
import jwt
from authlib.integrations.django_client import OAuth
from django.conf import settings

from skiflux.utils.social_auth import _get_apple_public_key

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

oauth.register(
    name="facebook",
    client_id=settings.FACEBOOK_APP_ID,
    client_secret=settings.FACEBOOK_APP_SECRET,
    access_token_url="https://graph.facebook.com/oauth/access_token",
    authorize_url="https://www.facebook.com/dialog/oauth",
    api_base_url="https://graph.facebook.com/",
    client_kwargs={"scope": "email public_profile"},
)


def get_google_auth_url(request) -> str:
    """Generates the Google OAuth consent page URL. Stores state in session."""
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return oauth.google.authorize_redirect(request, redirect_uri)


def exchange_google_code(request) -> dict:
    token = oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")
    if not user_info:
        resp = oauth.google.get(
            "https://openidconnect.googleapis.com/v1/userinfo", token=token
        )
        user_info = resp.json()
    return {
        "social_id": user_info["sub"],
        "email": user_info.get("email"),
        "first_name": user_info.get("given_name", ""),
        "last_name": user_info.get("family_name", ""),
        "avatar_url": user_info.get("picture"),
    }


def get_facebook_auth_url(request) -> str:
    """Generates the Facebook OAuth consent page URL."""
    redirect_uri = settings.FACEBOOK_REDIRECT_URI
    return oauth.facebook.authorize_redirect(request, redirect_uri)


def exchange_facebook_code(request) -> dict:
    token = oauth.facebook.authorize_access_token(request)
    resp = oauth.facebook.get(
        "me",
        token=token,
        params={"fields": "id,email,first_name,last_name,picture.type(large)"},
    )
    profile = resp.json()
    return {
        "social_id": profile["id"],
        "email": profile.get("email"),
        "first_name": profile.get("first_name", ""),
        "last_name": profile.get("last_name", ""),
        "avatar_url": profile.get("picture", {}).get("data", {}).get("url"),
    }


def _generate_apple_client_secret() -> str:
    now = int(time.time())
    headers = {"kid": settings.APPLE_KEY_ID}
    payload = {
        "iss": settings.APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 86400,
        "aud": "https://appleid.apple.com",
        "sub": settings.APPLE_CLIENT_ID,
    }
    return jwt.encode(
        payload, settings.APPLE_PRIVATE_KEY, algorithm="ES256", headers=headers
    )


def get_apple_auth_url() -> str:
    import urllib.parse

    params = {
        "client_id": settings.APPLE_CLIENT_ID,
        "redirect_uri": settings.APPLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "name email",
        "response_mode": "form_post",
    }
    return "https://appleid.apple.com/auth/authorize?" + urllib.parse.urlencode(params)


def exchange_apple_code(code: str, first_name: str = "", last_name: str = "") -> dict:
    client_secret = _generate_apple_client_secret()

    resp = httpx.post(
        "https://appleid.apple.com/auth/token",
        data={
            "client_id": settings.APPLE_CLIENT_ID,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.APPLE_REDIRECT_URI,
        },
    )
    token_data = resp.json()

    if "error" in token_data:
        raise ValueError(f"Apple token exchange failed: {token_data['error']}")

    raw_id_token = token_data["id_token"]

    try:
        header = jwt.get_unverified_header(raw_id_token)
        public_key = _get_apple_public_key(header["kid"])
        payload = jwt.decode(
            raw_id_token,
            public_key,
            algorithms=["RS256"],
            audience=settings.APPLE_CLIENT_ID,
            issuer="https://appleid.apple.com",
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("Apple token has expired.")
    except Exception as e:
        raise ValueError(f"Apple id_token verification failed: {e}")

    return {
        "social_id": payload["sub"],
        "email": payload.get("email"),
        "first_name": first_name,
        "last_name": last_name,
        "avatar_url": None,
    }
