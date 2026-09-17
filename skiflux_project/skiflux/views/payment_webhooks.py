import json
import logging

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from skiflux.gateways.registry import PaymentGatewayFactory
from skiflux.services.payment_service import PaymentService
from skiflux.services.withdrawal_service import WithdrawalService

logger = logging.getLogger(__name__)


@extend_schema(exclude=True)
class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, gateway_name, *args, **kwargs):
        # Read the raw body before any parsed access — signature verification
        # (Paystack, Stripe) requires the untouched bytes.
        raw_body = request.body
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in payment webhook from %s", gateway_name)
            return Response({"status": "invalid payload"}, status=400)

        payment_service = PaymentService()
        withdrawal_service = WithdrawalService()
        event = payload.get("event", "")

        if "transfer" in event.lower():
            try:
                gateway = PaymentGatewayFactory.get_gateway(gateway_name)
                if not gateway.verify_webhook_signature(
                    raw_body, request.headers, payload
                ):
                    logger.warning(
                        f"Invalid webhook signature for transfer event from {gateway_name}"  # noqa: E501
                    )
                    return Response({"status": "rejected"}, status=400)

                tx_ref = payload.get("data", {}).get("reference", "")
                if tx_ref.startswith("skf-wd-"):
                    req_id = tx_ref.replace("skf-wd-", "")
                    if (
                        payload.get("data", {}).get("status", "").lower()
                        == "successful"
                    ):
                        withdrawal_service.mark_withdrawal_completed(req_id)
                        logger.info(
                            f"Withdrawal {req_id} marked completed via webhook."
                        )
            except Exception as e:
                logger.error(
                    f"Error handling withdrawal webhook for {gateway_name}: {str(e)}",
                    exc_info=True,
                )
        else:
            try:
                success = payment_service.handle_webhook(
                    gateway_name, payload, raw_body, request.headers
                )
                if not success:
                    logger.warning(
                        "Payment webhook processing failed for %s event=%s",
                        gateway_name,
                        event,
                    )
            except Exception as e:
                logger.error(
                    "Error handling payment webhook for %s: %s",
                    gateway_name,
                    str(e),
                    exc_info=True,
                )

        return Response({"status": "received"})
