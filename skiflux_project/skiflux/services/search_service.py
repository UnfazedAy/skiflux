from rest_framework.exceptions import ValidationError
from rest_framework.utils.urls import replace_query_param

from skiflux.repositories.search_repository import SearchRepository


class SearchService:
    def __init__(self):
        self.search_repo = SearchRepository()

    def perform_search(self, request, query: str, limit: int = 10, offset: int = 0):
        if not query or len(query.strip()) < 2:
            raise ValidationError(
                {"q": "Search query must be at least 2 characters long."}
            )

        querysets = self.search_repo.get_search_querysets(query.strip())

        base_url = request.build_absolute_uri()

        paginated_results = {}
        for key, qs in querysets.items():
            total_count = qs.count()
            sliced_qs = list(qs[offset : offset + limit])
            if offset + limit < total_count:
                next_url = replace_query_param(base_url, "offset", offset + limit)
                next_url = replace_query_param(next_url, "limit", limit)
            else:
                next_url = None

            # Generate "previous" link
            if offset > 0:
                prev_offset = max(0, offset - limit)
                prev_url = replace_query_param(base_url, "offset", prev_offset)
                prev_url = replace_query_param(prev_url, "limit", limit)
            else:
                prev_url = None
            paginated_results[key] = {
                "count": total_count,
                "next": next_url,
                "previous": prev_url,
                "results": sliced_qs,
            }
        return paginated_results
