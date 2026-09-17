"""
Immutable ledger tests: transactions are never deleted; status tracks lifecycle.
"""

from decimal import Decimal

from django.core.cache import cache
from django.db.models import Sum
from django.test import TestCase

from skiflux.models.content import Episode, EpisodePurchase
from skiflux.models.role import Permission
from skiflux.models.wallet import (
    SkillcoinTransaction,
    SystemFinancialConfig,
    UserWallet,
)
from skiflux.services.content_service import ContentService
from skiflux.services.wallet_service import WalletService

from .conftest import (
    make_admin_with_role,
    make_creator,
    make_episode,
    make_season,
    make_verified_user,
)


class ImmutableLedgerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_verified_user(email="ledger@example.com")
        self.creator = make_creator(email="ledgercreator@skiflux.com")
        self.season = make_season(self.creator)
        config = SystemFinancialConfig.get_config()
        config.episode_purchase_price_skillcoins = Decimal("20.00")
        config.save()
        self.episode = make_episode(
            self.creator,
            self.season,
            access_type=Episode.AccessType.PAID,
            status=Episode.Status.PUBLISHED,
        )
        WalletService().credit_wallet(
            self.user,
            Decimal("100.00"),
            SkillcoinTransaction.Type.DEPOSIT,
            "Seed",
        )

    def test_refund_preserves_all_ledger_rows(self):
        ContentService().purchase_episode(self.user, str(self.episode.id))
        purchase = EpisodePurchase.objects.get(user=self.user, episode=self.episode)
        tx_count_before = SkillcoinTransaction.objects.count()

        economy_admin, _ = make_admin_with_role(
            [Permission.ECONOMY_MANAGE],
            email="ledgeradmin@skiflux.com",
        )
        ContentService().refund_episode_purchase(economy_admin, str(purchase.id))

        self.assertEqual(SkillcoinTransaction.objects.count(), tx_count_before + 5)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, EpisodePurchase.Status.REFUNDED)

        wallet = UserWallet.objects.get(user=self.user)
        ledger_sum = SkillcoinTransaction.objects.filter(
            wallet=wallet,
            status__in=SkillcoinTransaction.BALANCE_STATUSES,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        self.assertEqual(wallet.balance, ledger_sum)
        self.assertEqual(wallet.balance, Decimal("100.00"))
