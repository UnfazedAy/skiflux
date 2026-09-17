from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from skiflux.serializers.search import GlobalSearchResponseSerializer
from skiflux.services.search_service import SearchService


class SearchViewSet(ViewSet):
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search_service = SearchService()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="q", description="Search query", required=True, type=str
            ),
            OpenApiParameter(
                name="limit",
                description="Items per category",
                required=False,
                type=int,
                default=10,
            ),
            OpenApiParameter(
                name="offset",
                description="Pagination offset",
                required=False,
                type=int,
                default=0,
            ),
        ],
        responses={200: GlobalSearchResponseSerializer},
        summary="Global paginated search",
        tags=["User › Content"],
    )
    def list(self, request):
        query = request.query_params.get("q", "")
        limit = int(request.query_params.get("limit", 10))
        limit = min(limit, 50)
        offset = int(request.query_params.get("offset", 0))

        results_dict = self.search_service.perform_search(request, query, limit, offset)

        serializer = GlobalSearchResponseSerializer(
            results_dict,
            context={"request": request},
        )
        return Response(serializer.data)
