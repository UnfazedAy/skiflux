from django.urls import path

from skiflux.views.payment_webhooks import PaymentWebhookView
from skiflux.views.webhooks import CloudinaryEagerWebhookView

urlpatterns = [
    path(
        "webhooks/cloudinary/eager/",
        CloudinaryEagerWebhookView.as_view(),
        name="cloudinary-eager-webhook",
    ),
    path(
        "webhooks/payment/flutterwave/",
        PaymentWebhookView.as_view(),
        {"gateway_name": "flutterwave"},
        name="webhook-flutterwave",
    ),
    path(
        "webhooks/payment/paystack/",
        PaymentWebhookView.as_view(),
        {"gateway_name": "paystack"},
        name="webhook-paystack",
    ),
    path(
        "webhooks/payment/stripe/",
        PaymentWebhookView.as_view(),
        {"gateway_name": "stripe"},
        name="webhook-stripe",
    ),
]
