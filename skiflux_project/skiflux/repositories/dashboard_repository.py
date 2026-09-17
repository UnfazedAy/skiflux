from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum, Count
from django.utils import timezone
from django.db.models.functions import TruncMonth

from skiflux.models import AdminUser, User
from skiflux.models.content import Episode
from skiflux.models.wallet import SkillcoinTransaction, UserWallet
from skiflux.models.platform_settings import SystemContentConfig


class DashboardRepository:
    def count_total_users(self, created_before=None) -> int:
        queryset = User.objects.filter(is_staff=False, is_superuser=False)
        if created_before is not None:
            queryset = queryset.filter(created_at__lt=created_before)
        return queryset.count()

    def count_active_creators(self, created_before=None) -> int:
        queryset = AdminUser.objects.filter(
            AdminUser.creators_filter(),
            status=AdminUser.Status.ACTIVE,
            is_active=True,
        )
        if created_before is not None:
            queryset = queryset.filter(created_at__lt=created_before)
        return queryset.count()

    def get_total_skillcoins_in_circulation(self) -> Decimal:
        result = UserWallet.objects.aggregate(total=Sum("balance"))
        return result["total"] or Decimal("0.00")

    def get_revenue_last_24h(self) -> Decimal:
        since = timezone.now() - timedelta(hours=24)
        aggregate = SkillcoinTransaction.objects.filter(
            wallet__is_platform_wallet=True,
            transaction_type=SkillcoinTransaction.Type.PLATFORM_REVENUE,
            status=SkillcoinTransaction.Status.POSTED,
            created_at__gte=since,
        ).aggregate(total=Sum("amount"))
        return aggregate["total"] or Decimal("0.00")

    def get_total_platform_revenue(self) -> Decimal:
        aggregate = SkillcoinTransaction.objects.filter(
            wallet__is_platform_wallet=True,
            transaction_type=SkillcoinTransaction.Type.PLATFORM_REVENUE,
            status=SkillcoinTransaction.Status.POSTED,
        ).aggregate(total=Sum("amount"))
        return aggregate["total"] or Decimal("0.00")

    def count_pending_verifications(self) -> int:
        return Episode.objects.filter(status=Episode.Status.REVIEW).count()

    def count_high_priority_pending_verifications(self) -> int:
        sla_hours = SystemContentConfig.get_config().sla_review_hours
        sla_cutoff = timezone.now() - timedelta(hours=sla_hours)
        return Episode.objects.filter(
            status=Episode.Status.REVIEW,
            submitted_for_review_at__isnull=False,
            submitted_for_review_at__lte=sla_cutoff,
        ).count()

    def get_user_growth_by_month(self, months: int = 6) -> dict:
        now = timezone.now()
        since = now - timedelta(days=30 * months)
        since_last_year = since - timedelta(days=365)
        end_last_year = now - timedelta(days=365)

        data = (
            User.objects.filter(
                created_at__gte=since,
            )
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )

        current_total = User.objects.filter(
            created_at__gte=since,
        ).count()

        last_year_total = User.objects.filter(
            created_at__gte=since_last_year,
            created_at__lt=end_last_year,
        ).count()

        if last_year_total > 0:
            percentage_change = (
                (current_total - last_year_total) / last_year_total
            ) * 100
        else:
            percentage_change = 100.0 if current_total > 0 else 0.0

        return {
            "data": data,
            "percentage_change": round(percentage_change, 1),
            "is_increase": percentage_change > 0,
        }
