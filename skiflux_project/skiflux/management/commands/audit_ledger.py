from django.core.management.base import BaseCommand

from skiflux.models import User
from skiflux.services.wallet_service import WalletService


class Command(BaseCommand):
    help = (
        "Audits all platform wallets, flags cached "
        "balance mismatches, and auto-locks compromised records."
    )

    def handle(self, *args, **options):
        self.stdout.write("Initializing system-wide Skillcoin Ledger Audit...")

        wallet_service = WalletService()
        users = User.objects.all()

        total_audited = 0
        failures = 0

        for user in users:
            try:
                results = wallet_service.audit_wallet_integrity(user)
                total_audited += 1

                if not results["is_valid"]:
                    failures += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"COMPROMISED WALLET! Email: {user.email} | "
                            f"Cached: {results['cached_balance']} | Ledger Sum: {results['ledger_sum']} "  # noqa: E501
                            f"--> Auto-Lock Imposed."
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Verified: {user.email} | Balance: {results['cached_balance']}"  # noqa: E501
                        )
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error auditing user {user.email}: {e}")
                )

        self.stdout.write("\n==================================================")
        self.stdout.write(f"Audit Complete. Total Wallets Audited: {total_audited}")
        if failures > 0:
            self.stdout.write(
                self.style.ERROR(f"CRITICAL: Found {failures} compromised wallet(s).")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("System integrity confirmed. 100% records matching.")
            )
