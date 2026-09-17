from rest_framework.pagination import PageNumberPagination

from .responses import APIResponse


class RecommendationPaginator(PageNumberPagination):
    page_size = 10
    page_size_query_param = "limit"
    max_page_size = 50
    page_query_param = "page"

    def get_paginated_response(self, data, message="Data retrieved successfully"):
        payload = {
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            data=payload,
            message=message,
        )


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data, message="Data retrieved successfully"):
        payload = {
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            data=payload,
            message=message,
        )
