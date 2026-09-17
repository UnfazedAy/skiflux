from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("api/v1/", include("skiflux.urls.auth")),
    path("api/v1/", include("skiflux.urls.admin")),
    path("api/v1/", include("skiflux.urls.creator")),
    path("api/v1/", include("skiflux.urls.content")),
    path("api/v1/", include("skiflux.urls.webhooks")),
    path("api/v1/", include("skiflux.urls.wallet")),
    path("api/v1/", include("skiflux.urls.search")),
    path("api/v1/", include("skiflux.urls.profile")),
    path("api/v1/", include("skiflux.urls.users")),
    path("api/v1/", include("skiflux.urls.investor")),
    path("api/v1/profile/", include("skiflux.urls.profile")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
