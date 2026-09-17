from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from skiflux.repositories.dashboard_repository import DashboardRepository


class DashboardService:
    def __init__(self, repository: DashboardRepository | None = None):
        self.repository = repository or DashboardRepository()

    @staticmethod
    def _growth_percentage(current: int, previous: int) -> Decimal:
        if previous == 0:
            return Decimal("100.0") if current > 0 else Decimal("0.0")
        growth = ((current - previous) / previous) * 100
        return Decimal(str(growth)).quantize(Decimal("0.1"))

    def get_overview(self) -> dict:
        comparison_cutoff = timezone.now() - timedelta(hours=24)

        total_users = self.repository.count_total_users()
        previous_total_users = self.repository.count_total_users(
            created_before=comparison_cutoff
        )

        active_creators = self.repository.count_active_creators()
        previous_active_creators = self.repository.count_active_creators(
            created_before=comparison_cutoff
        )

        pending_verifications = self.repository.count_pending_verifications()

        return {
            "total_users": total_users,
            "total_users_growth_percentage": self._growth_percentage(
                total_users,
                previous_total_users,
            ),
            "active_creators": active_creators,
            "active_creators_growth_percentage": self._growth_percentage(
                active_creators,
                previous_active_creators,
            ),
            "revenue_last_24h": self.repository.get_total_skillcoins_in_circulation(),
            "pending_verifications": pending_verifications,
            "is_pending_verifications_high_priority": (
                self.repository.count_high_priority_pending_verifications() > 0
            ),
        }

    def get_user_growth(self, months: int = 6) -> dict:
        return self.repository.get_user_growth_by_month(months=months)
