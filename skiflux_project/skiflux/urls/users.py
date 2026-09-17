from django.urls import path

from skiflux.views.users import (
    get_public_user_profile,
    get_public_user_profile_by_username,
)

urlpatterns = [
    path(
        "users/<uuid:user_id>",
        get_public_user_profile,
        name="public-user-profile",
    ),
    path(
        "users/by-username/<str:username>",
        get_public_user_profile_by_username,
        name="public-user-profile-by-username",
    ),
]
