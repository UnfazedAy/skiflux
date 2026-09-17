from django.urls import path

from skiflux.views.search import SearchViewSet

urlpatterns = [
    path("search", SearchViewSet.as_view({"get": "list"}), name="global-search"),
]
