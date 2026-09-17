from django.urls import path

from skiflux.views.investor import submit_investor_review

urlpatterns = [
    path(
        "investor/review/",
        submit_investor_review,
        name="investor-review-submit",
    ),
]
