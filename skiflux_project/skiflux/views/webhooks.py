import logging

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from skiflux.tasks.content import process_cloudinary_eager_webhook_task
from skiflux.utils.cloudinary_notifications import (
    parse_cloudinary_notification_body,
    verify_cloudinary_notification,
)

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class CloudinaryEagerWebhookView(APIView):
    """Receives Cloudinary eager_async completion notifications."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def post(self, request):
        if not verify_cloudinary_notification(request):
            return Response({"error": "Invalid signature"}, status=401)

        payload = parse_cloudinary_notification_body(request)
        process_cloudinary_eager_webhook_task.delay(payload)
        return Response({"status": "accepted"}, status=200)
