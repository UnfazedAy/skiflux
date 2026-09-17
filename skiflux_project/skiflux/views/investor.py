from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny

from skiflux.serializers.investor import (
    InvestorReviewResponseSerializer,
    InvestorReviewSubmitSerializer,
)
from skiflux.services.investor_service import InvestorService
from skiflux.utils import APIResponse, InvestorSubmitRateThrottle

_INVESTOR_TAGS = ["Investor › Review"]


@extend_schema(
    summary="Submit investor review",
    description=(
        "Accepts the complete investor landing page submission, saves it to the "
        "database, and sends a confirmation email to the investor."
    ),
    request=InvestorReviewSubmitSerializer,
    responses={
        201: OpenApiResponse(
            description="Investor review submitted successfully.",
            response=InvestorReviewResponseSerializer,
        ),
        400: OpenApiResponse(description="Validation error."),
    },
    tags=_INVESTOR_TAGS,
    operation_id="investor_review_submit",
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([InvestorSubmitRateThrottle])
def submit_investor_review(request):
    serializer = InvestorReviewSubmitSerializer(data=request.data)
    if not serializer.is_valid():
        return APIResponse(
            status="error",
            status_code=status.HTTP_400_BAD_REQUEST,
            message=serializer.errors,
        )

    service = InvestorService()
    try:
        review = service.submit_review(serializer.validated_data)
    except Exception:
        return APIResponse(
            status="error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=(
                "We could not save your investor profile right now. "
                "Please try again shortly."
            ),
        )

    response_data = service.serialize_review(review)
    response_serializer = InvestorReviewResponseSerializer(data=response_data)
    response_serializer.is_valid(raise_exception=True)

    return APIResponse(
        status="success",
        status_code=status.HTTP_201_CREATED,
        message="Investor review submitted successfully.",
        data=response_serializer.data,
    )
