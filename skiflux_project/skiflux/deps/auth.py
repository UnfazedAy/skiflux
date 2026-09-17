from functools import wraps

from django.http import JsonResponse

from skiflux.models import User
from skiflux.utils import decode_token


def custom_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return JsonResponse(
                {"error": "Unauthorized, missing Bearer token"},
                status=401,
            )

        token = auth_header.split(" ")[1]

        try:
            payload = decode_token(token, scope="user")
            if payload.get("type") != "access":
                return JsonResponse(
                    {"error": "Invalid token type, expected access token"},
                    status=401,
                )
            user = User.objects.get(id=payload["user_id"])
            request.custom_user = user

        except (ValueError, TypeError) as e:
            return JsonResponse({"error": str(e)}, status=401)
        except User.DoesNotExist:
            return JsonResponse({"error": "User no longer exists"}, status=401)

        return view_func(request, *args, **kwargs)

    return wrapper
