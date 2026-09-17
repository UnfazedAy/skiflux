import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from skiflux.gateways.flutterwave import FlutterwaveGateway
from skiflux.gateways.paystack import PaystackGateway
from skiflux.gateways.payment_channels import (
    flutterwave_payment_options,
    paystack_channels,
)


class TestPaymentChannelMapping:
    def test_paystack_channels_card(self):
        assert paystack_channels("card") == ["card"]

    def test_paystack_channels_bank_transfer(self):
        assert paystack_channels("bank_transfer") == ["bank_transfer"]

    def test_paystack_channels_all(self):
        assert paystack_channels("all") is None

    def test_flutterwave_payment_options_card(self):
        assert flutterwave_payment_options("card") == "card"

    def test_flutterwave_payment_options_bank_transfer(self):
        assert flutterwave_payment_options("bank_transfer") == "banktransfer"

    def test_flutterwave_payment_options_all(self):
        assert flutterwave_payment_options("all") is None


@pytest.mark.django_db
class TestGatewayInitiatePaymentChannels:
    @patch("skiflux.gateways.paystack.requests.post")
    def test_paystack_initiate_payment_passes_channels(self, mock_post, settings):
        settings.PAYSTACK_SECRET_KEY = "sk_test"
        mock_post.return_value = MagicMock(
            status_code=200,
            raise_for_status=MagicMock(),
            json=MagicMock(
                return_value={
                    "status": True,
                    "data": {
                        "reference": "ref-1",
                        "authorization_url": "https://paystack.com/pay/1",
                    },
                }
            ),
        )

        PaystackGateway().initiate_payment(
            amount=Decimal("1000.00"),
            email="user@test.com",
            tx_ref="skf-topup-abc",
            payment_method="card",
        )

        payload = mock_post.call_args.kwargs["json"]
        assert payload["channels"] == ["card"]

    @patch("skiflux.gateways.flutterwave.requests.post")
    def test_flutterwave_initiate_payment_passes_payment_options(
        self, mock_post, settings
    ):
        settings.FLUTTERWAVE_SECRET_KEY = "sk_test"
        mock_post.return_value = MagicMock(
            status_code=200,
            raise_for_status=MagicMock(),
            json=MagicMock(
                return_value={
                    "status": "success",
                    "data": {"id": "1", "link": "https://flw.com/pay/1"},
                }
            ),
        )

        FlutterwaveGateway().initiate_payment(
            amount=Decimal("1000.00"),
            email="user@test.com",
            tx_ref="skf-topup-abc",
            payment_method="bank_transfer",
        )

        payload = mock_post.call_args.kwargs["json"]
        assert payload["payment_options"] == "banktransfer"
