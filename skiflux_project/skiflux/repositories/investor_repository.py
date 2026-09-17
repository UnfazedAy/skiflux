from skiflux.models.investor import InvestorReview


class InvestorRepository:
    def create(self, **kwargs) -> InvestorReview:
        return InvestorReview.objects.create(**kwargs)

    def list_queryset(self, email: str | None = None):
        qs = InvestorReview.objects.all().order_by("-submitted_at")
        if email:
            qs = qs.filter(email__iexact=email.strip())
        return qs

    def get_by_id(self, review_id) -> InvestorReview | None:
        try:
            return InvestorReview.objects.get(pk=review_id)
        except InvestorReview.DoesNotExist:
            return None
