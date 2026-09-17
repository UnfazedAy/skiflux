from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated

from skiflux.models import AdminUser, User
from skiflux.utils.auth import AdminJWTAuthentication
from skiflux.utils.lockout import manually_unlock_account
from skiflux.utils.permissions import IsSuperAdmin
from skiflux.utils.responses import APIResponse


@extend_schema(tags=["Admin › Accounts"])
@api_view(["POST"])
@authentication_classes([AdminJWTAuthentication])
@permission_classes([IsAuthenticated, IsSuperAdmin])
def unlock_user_account(request):
    email = request.data.get("email")
    if not email:
        return APIResponse(
            status="error", status_code=400, message="Email is required."
        )

    unlocked = False
    for Model in (User, AdminUser):
        obj = Model.objects.filter(email=email).first()
        if obj:
            manually_unlock_account(obj)
            unlocked = True
            break

    if not unlocked:
        return APIResponse(status="error", status_code=404, message="User not found.")

    return APIResponse(
        status="success",
        status_code=status.HTTP_200_OK,
        message=f"Account {email} has been manually unlocked.",
    )
