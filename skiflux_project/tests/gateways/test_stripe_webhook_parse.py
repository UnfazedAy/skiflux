from decimal import Decimal

from skiflux.gateways.stripe_gateway import StripeGateway


class TestStripeWebhookParse:
    def test_checkout_session_completed_setup_mode_null_amount(self):
        gateway = StripeGateway()
        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "object": "checkout.session",
                    "id": "cs_test_123",
                    "mode": "setup",
                    "payment_status": "no_payment_required",
                    "client_reference_id": "skf-card-abc123",
                    "amount_total": None,
                    "currency": None,
                    "setup_intent": "seti_test_123",
                    "customer": "cus_test_123",
                }
            },
        }

        result = gateway.parse_webhook_payload(payload)

        assert result.tx_ref == "skf-card-abc123"
        assert result.is_successful is True
        assert result.amount_paid == Decimal("0.00")

    def test_setup_intent_succeeded_uses_metadata_tx_ref(self):
        gateway = StripeGateway()
        payload = {
            "type": "setup_intent.succeeded",
            "data": {
                "object": {
                    "object": "setup_intent",
                    "id": "seti_test_123",
                    "status": "succeeded",
                    "metadata": {"tx_ref": "skf-card-xyz789"},
                    "payment_method": "pm_test_123",
                    "customer": "cus_test_123",
                }
            },
        }

        result = gateway.parse_webhook_payload(payload)

        assert result.tx_ref == "skf-card-xyz789"
        assert result.is_successful is True
        assert result.amount_paid == Decimal("0.00")
