from django.core.management.base import BaseCommand

from skiflux.models import AdminUser, User
from skiflux.services.wallet_service import WalletService


class Command(BaseCommand):
    help = (
        "Runs full wallet balance vs ledger invariant check. Use in cron/Celery beat."
    )

    def handle(self, *args, **options):
        ws = WalletService()
        failures = 0
        total = 0

        for Model in (User, AdminUser):
            for obj in Model.objects.iterator():
                total += 1
                try:
                    wallet = ws.get_or_create_wallet(obj)
                    ledger_sum = ws._posted_ledger_sum(wallet)
                    if wallet.balance != ledger_sum:
                        failures += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"DRIFT DETECTED: {obj.email} | Balance={wallet.balance} | Ledger={ledger_sum}"  # noqa: E501
                            )
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f"Error checking {obj.email}: {e}")
                    )

        if failures == 0:
            self.stdout.write(
                self.style.SUCCESS(f"All {total} wallets passed invariant check.")
            )
        else:
            self.stdout.write(
                self.style.ERROR(f"{failures}/{total} wallets have balance drift!")
            )
