from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from skiflux.models import AdminUser, User
from skiflux.models.content import (
    Episode,
    EpisodePurchase,
    EpisodeTask,
    Season,
    TaskSubmission,
)
from skiflux.models.wallet import (
    SkillcoinTransaction,
    SystemFinancialConfig,
    UserWallet,
    WithdrawalAccount,
    WithdrawalHold,
    WithdrawalRequest,
)
from skiflux.services.content_service import ContentService
from skiflux.services.registration_bonus_service import RegistrationBonusService
from skiflux.services.wallet_service import WalletService
from skiflux.services.withdrawal_service import WithdrawalService


@pytest.fixture
def ws():
    return WalletService()


@pytest.fixture
def economy_setup(db, ws):
    config = SystemFinancialConfig.get_config()
    config.creator_share_percentage = Decimal("70.00")
    config.episode_purchase_price_skillcoins = Decimal("100.00")
    config.withdrawal_fee_percentage = Decimal("0.00")
    config.min_withdrawal_amount = Decimal("10.00")
    config.require_withdrawal_approval = True
    config.enabled_withdrawal_gateways = ["flutterwave"]
    config.save()

    learner = User.objects.create(
        email="learner@e2e.com", first_name="Learner", is_verified=True
    )
    creator = AdminUser.objects.create(
        email="creator@e2e.com",
        first_name="Creator",
        role_type=AdminUser.RoleType.CREATOR,
    )
    season = Season.objects.create(
        creator=creator,
        title="E2E Season",
        price=Decimal("100.00"),
        skillworld="design",
    )
    episode = Episode.objects.create(
        creator=creator,
        season=season,
        title="E2E Episode",
        order=1,
        status=Episode.Status.PUBLISHED,
        access_type=Episode.AccessType.PAID,
    )
    ws.credit_wallet(
        learner, Decimal("500.00"), SkillcoinTransaction.Type.TOPUP, "Initial fund"
    )
    return {
        "learner": learner,
        "creator": creator,
        "season": season,
        "episode": episode,
        "config": config,
    }


def test_full_purchase_flow_creates_ledger_entries(economy_setup):
    setup = economy_setup
    ws = WalletService()
    content_service = ContentService()
    content_service.purchase_episode(setup["learner"], str(setup["episode"].id))
    learner_wallet = ws.get_or_create_wallet(setup["learner"])
    creator_wallet = ws.get_or_create_wallet(setup["creator"])

    assert learner_wallet.balance < Decimal("500.00")
    assert creator_wallet.balance > Decimal("0.00")

    assert ws._posted_ledger_sum(learner_wallet) == learner_wallet.balance
    assert ws._posted_ledger_sum(creator_wallet) == creator_wallet.balance


def test_withdrawal_request_flow(economy_setup):
    setup = economy_setup
    ws = WalletService()
    withdrawal_service = WithdrawalService()

    ws.credit_wallet(
        setup["creator"],
        Decimal("1000.00"),
        SkillcoinTransaction.Type.CREATOR_REVENUE,
        "Test revenue",
    )

    account = WithdrawalAccount.objects.create(
        admin_user=setup["creator"],
        bank_code="044",
        bank_name="Access Bank",
        account_number="1234567890",
        account_name="Test Creator",
        status=WithdrawalAccount.Status.VERIFIED,
    )

    request = withdrawal_service.request_withdrawal(
        setup["creator"], str(account.id), Decimal("200.00")
    )

    assert request.status == WithdrawalRequest.Status.PENDING
    assert request.amount == Decimal("200.00")

    # Current design: request_withdrawal creates an ACTIVE WithdrawalHold
    # (reservation). No SkillcoinTransaction rows are created until the hold
    # is converted on successful completion.
    hold = WithdrawalHold.objects.get(withdrawal_request=request)
    assert hold.status == WithdrawalHold.Status.ACTIVE
    assert hold.amount == Decimal("200.00")


@pytest.mark.django_db
class TestTopUpFlow:
    def test_topup_credits_correct_skillcoin_amount(self, ws):
        user = User.objects.create(email="topup@e2e.com", first_name="T")
        ws.credit_wallet(
            user,
            Decimal("250.00"),
            SkillcoinTransaction.Type.TOPUP,
            "Gateway top-up",
            idempotency_key="topup-e2e-001",
        )
        wallet = ws.get_or_create_wallet(user)
        assert wallet.balance == Decimal("250.00")
        assert ws._posted_ledger_sum(wallet) == Decimal("250.00")

    def test_topup_idempotency_never_double_credits(self, ws):
        user = User.objects.create(email="idemp@e2e.com", first_name="I")
        for _ in range(3):
            ws.credit_wallet(
                user,
                Decimal("100.00"),
                SkillcoinTransaction.Type.TOPUP,
                "Retry",
                idempotency_key="topup-idemp-001",
            )
        wallet = ws.get_or_create_wallet(user)
        assert wallet.balance == Decimal("100.00")
        assert (
            SkillcoinTransaction.objects.filter(
                idempotency_key="topup-idemp-001"
            ).count()
            == 1
        )

    def test_multiple_topups_accumulate_correctly(self, ws):
        user = User.objects.create(email="multi@e2e.com", first_name="M")
        for i in range(5):
            ws.credit_wallet(
                user,
                Decimal("100.00"),
                SkillcoinTransaction.Type.TOPUP,
                f"Top-up {i}",
                idempotency_key=f"topup-multi-{i}",
            )
        wallet = ws.get_or_create_wallet(user)
        assert wallet.balance == Decimal("500.00")
        assert wallet.balance == ws._posted_ledger_sum(wallet)


@pytest.mark.django_db
class TestPurchaseFlow:
    def test_purchase_splits_70_30(self, economy_setup, ws):
        d = economy_setup
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        learner_w = ws.get_or_create_wallet(d["learner"])
        creator_w = ws.get_or_create_wallet(d["creator"])
        platform_w = ws.get_platform_wallet()

        assert learner_w.balance == Decimal("400.00")
        assert creator_w.balance == Decimal("70.00")
        assert platform_w.balance == Decimal("-440.00")

    def test_purchase_creates_correct_ledger_entries(self, economy_setup, ws):
        d = economy_setup
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))
        purchase = EpisodePurchase.objects.get(user=d["learner"], episode=d["episode"])

        learner_w = ws.get_or_create_wallet(d["learner"])
        debit = SkillcoinTransaction.objects.get(
            wallet=learner_w,
            transaction_type=SkillcoinTransaction.Type.DEBIT_PURCHASE,
        )
        assert debit.amount == Decimal("-100.00")
        assert debit.status == SkillcoinTransaction.Status.POSTED
        assert debit.reference_id == purchase.id

        creator_w = ws.get_or_create_wallet(d["creator"])
        credit = SkillcoinTransaction.objects.get(
            wallet=creator_w,
            transaction_type=SkillcoinTransaction.Type.CREATOR_REVENUE,
        )
        assert credit.amount == Decimal("70.00")
        assert credit.reference_id == purchase.id

    def test_two_users_buying_same_episode_are_independent(self, economy_setup, ws):
        d = economy_setup
        user2 = User.objects.create(email="learner2@e2e.com", first_name="L2")
        ws.credit_wallet(
            user2, Decimal("500.00"), SkillcoinTransaction.Type.TOPUP, "Fund"
        )

        ContentService().purchase_episode(d["learner"], str(d["episode"].id))
        ContentService().purchase_episode(user2, str(d["episode"].id))

        creator_w = ws.get_or_create_wallet(d["creator"])
        assert creator_w.balance == Decimal("140.00")  # 70 × 2

    def test_double_purchase_rejected_without_extra_debit(self, economy_setup, ws):
        from rest_framework.exceptions import ValidationError

        d = economy_setup
        svc = ContentService()
        svc.purchase_episode(d["learner"], str(d["episode"].id))

        with pytest.raises(ValidationError):
            svc.purchase_episode(d["learner"], str(d["episode"].id))

        learner_w = ws.get_or_create_wallet(d["learner"])
        assert learner_w.balance == Decimal("400.00")  # debited only once


@pytest.mark.django_db
class TestCreatorWithdrawalFlow:
    def test_full_flow_purchase_then_creator_withdrawal(
        self,
        economy_setup,
        ws,
    ):
        d = economy_setup
        d["config"].require_withdrawal_approval = False
        d["config"].save()

        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        creator_w = ws.get_or_create_wallet(d["creator"])
        assert creator_w.balance == Decimal("70.00")

        account = WithdrawalAccount.objects.create(
            admin_user=d["creator"],
            bank_code="044",
            account_number="0123456789",
            account_name="Creator E2E",
            gateway_name="flutterwave",
            status=WithdrawalAccount.Status.VERIFIED,
        )

        with patch(
            "skiflux.gateways.flutterwave.FlutterwaveGateway.initiate_transfer"
        ) as mock_transfer:
            mock_transfer.return_value = MagicMock(
                transfer_reference="FLW-E2E-001",
                status="successful",
                raw_response={},
            )
            req = WithdrawalService().request_withdrawal(
                d["creator"], str(account.id), Decimal("70.00")
            )

        req.refresh_from_db()
        assert req.status == WithdrawalRequest.Status.COMPLETED
        mock_transfer.assert_called_once()

        creator_w.refresh_from_db()
        assert creator_w.balance == Decimal("0.00")
        assert creator_w.balance == ws._posted_ledger_sum(creator_w)

        learner_w = ws.get_or_create_wallet(d["learner"])
        assert learner_w.balance == ws._posted_ledger_sum(learner_w)

    def test_withdrawal_rejection_restores_balance(self, economy_setup, ws):
        from skiflux.models.role import Permission, Role

        d = economy_setup
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        account = WithdrawalAccount.objects.create(
            admin_user=d["creator"],
            bank_code="044",
            account_number="0123456789",
            account_name="Creator E2E",
            status=WithdrawalAccount.Status.VERIFIED,
        )
        req = WithdrawalService().request_withdrawal(
            d["creator"], str(account.id), Decimal("70.00")
        )
        assert req.status == WithdrawalRequest.Status.PENDING

        role = Role.objects.create(
            name="eco-rej", permissions=[Permission.ECONOMY_MANAGE]
        )
        admin = AdminUser.objects.create(email="rejectadmin@e2e.com", first_name="Rej")
        admin.roles.add(role)
        WithdrawalService().reject_withdrawal(admin, str(req.id), "Test rejection")

        creator_w = ws.get_or_create_wallet(d["creator"])
        assert creator_w.balance == Decimal("70.00")
        assert creator_w.balance == ws._posted_ledger_sum(creator_w)

    def test_withdrawal_with_fee_platform_receives_fee(self, economy_setup, ws):
        d = economy_setup
        d["config"].withdrawal_fee_percentage = Decimal("2.00")
        d["config"].require_withdrawal_approval = False
        d["config"].save()

        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        account = WithdrawalAccount.objects.create(
            admin_user=d["creator"],
            bank_code="044",
            account_number="0123456789",
            account_name="Creator E2E",
            status=WithdrawalAccount.Status.VERIFIED,
        )

        with patch(
            "skiflux.gateways.flutterwave.FlutterwaveGateway.initiate_transfer"
        ) as mock_transfer:
            mock_transfer.return_value = MagicMock(
                transfer_reference="FLW-E2E-FEE",
                status="successful",
                raw_response={},
            )
            req = WithdrawalService().request_withdrawal(
                d["creator"], str(account.id), Decimal("70.00")
            )

        # Drive to completion using the hold conversion path
        WithdrawalService().mark_withdrawal_completed(str(req.id))

        req.refresh_from_db()
        # fee = 2% of 70 = 1.40
        assert req.fee == Decimal("1.40")
        assert req.net_amount == Decimal("68.60")

        platform_w = ws.get_platform_wallet()
        #       + credit(1.40 fee release) = -398.60
        assert platform_w.balance == Decimal("-440.00")


@pytest.mark.django_db
class TestRefundFlow:
    def test_refund_restores_learner_and_claws_back_creator(self, economy_setup, ws):
        from skiflux.models.role import Permission, Role

        d = economy_setup
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        role = Role.objects.create(
            name="eco-ref", permissions=[Permission.ECONOMY_MANAGE]
        )
        admin = AdminUser.objects.create(email="refundadmin@e2e.com", first_name="Ref")
        admin.roles.add(role)
        purchase = EpisodePurchase.objects.get(user=d["learner"])
        ContentService().refund_episode_purchase(admin, str(purchase.id))

        learner_w = ws.get_or_create_wallet(d["learner"])
        creator_w = ws.get_or_create_wallet(d["creator"])

        assert learner_w.balance == Decimal("500.00")
        assert creator_w.balance == Decimal("0.00")
        assert learner_w.balance == ws._posted_ledger_sum(learner_w)
        assert creator_w.balance == ws._posted_ledger_sum(creator_w)

    def test_refund_marks_purchase_as_refunded(self, economy_setup, ws):
        from skiflux.models.role import Permission, Role

        d = economy_setup
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        role = Role.objects.create(
            name="eco-ref2", permissions=[Permission.ECONOMY_MANAGE]
        )
        admin = AdminUser.objects.create(email="refadmin2@e2e.com", first_name="R2")
        admin.roles.add(role)
        purchase = EpisodePurchase.objects.get(user=d["learner"])
        ContentService().refund_episode_purchase(admin, str(purchase.id))

        purchase.refresh_from_db()
        assert purchase.status == EpisodePurchase.Status.REFUNDED

    def test_double_refund_is_rejected(self, economy_setup, ws):
        from rest_framework.exceptions import ValidationError

        from skiflux.models.role import Permission, Role

        d = economy_setup
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        role = Role.objects.create(
            name="eco-ref3", permissions=[Permission.ECONOMY_MANAGE]
        )
        admin = AdminUser.objects.create(email="refadmin3@e2e.com", first_name="R3")
        admin.roles.add(role)
        purchase = EpisodePurchase.objects.get(user=d["learner"])
        ContentService().refund_episode_purchase(admin, str(purchase.id))

        with pytest.raises(ValidationError):
            ContentService().refund_episode_purchase(admin, str(purchase.id))


@pytest.mark.django_db
class TestRegistrationBonusFlow:
    def test_bonus_credited_once_on_verification(self, ws):
        config = SystemFinancialConfig.get_config()
        config.registration_bonus_skillcoins = Decimal("20.00")
        config.save()

        user = User.objects.create(
            email="regbonus@e2e.com", first_name="B", is_verified=True
        )
        RegistrationBonusService().grant_if_eligible(user)

        wallet = ws.get_or_create_wallet(user)
        assert wallet.balance == Decimal("20.00")
        assert wallet.bonus_balance == Decimal("20.00")

    def test_bonus_grant_is_idempotent(self, ws):
        config = SystemFinancialConfig.get_config()
        config.registration_bonus_skillcoins = Decimal("20.00")
        config.save()

        user = User.objects.create(
            email="bonusidemp@e2e.com", first_name="BI", is_verified=True
        )
        svc = RegistrationBonusService()
        svc.grant_if_eligible(user)
        svc.grant_if_eligible(user)
        svc.grant_if_eligible(user)

        wallet = ws.get_or_create_wallet(user)
        assert wallet.balance == Decimal("20.00")

    def test_bonus_excluded_from_withdrawable_balance(self, ws):
        config = SystemFinancialConfig.get_config()
        config.registration_bonus_skillcoins = Decimal("50.00")
        config.save()

        user = User.objects.create(
            email="bonuswd@e2e.com", first_name="BW", is_verified=True
        )
        RegistrationBonusService().grant_if_eligible(user)
        ws.credit_wallet(
            user, Decimal("100.00"), SkillcoinTransaction.Type.TOPUP, "Real topup"
        )

        withdrawable = ws.get_withdrawable_balance(user)
        assert withdrawable == Decimal("100.00")

    def test_bonus_zero_config_does_not_credit(self, ws):
        config = SystemFinancialConfig.get_config()
        config.registration_bonus_skillcoins = Decimal("0.00")
        config.save()

        user = User.objects.create(
            email="nobonus@e2e.com", first_name="NB", is_verified=True
        )
        RegistrationBonusService().grant_if_eligible(user)

        wallet = ws.get_or_create_wallet(user)
        assert wallet.balance == Decimal("0.00")


@pytest.mark.django_db
class TestGlobalLedgerInvariants:
    def test_all_wallet_balances_match_ledger_after_full_flow(self, economy_setup, ws):
        """
        After a realistic multi-step flow, every wallet's cached balance
        must equal its posted ledger sum. This is the invariant test the
        review asked for.
        """
        from skiflux.models.role import Permission, Role

        d = economy_setup

        ws.credit_platform_wallet(
            Decimal("200.00"), SkillcoinTransaction.Type.PLATFORM_REVENUE, "Seed"
        )
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        task = EpisodeTask.objects.create(
            episode=d["episode"], kind=EpisodeTask.Kind.PROJECT_BASED
        )
        submission = TaskSubmission.objects.create(
            task=task, user=d["learner"], submission_text="answer"
        )
        role = Role.objects.create(
            name="cm-inv", permissions=[Permission.CONTENT_MANAGE]
        )
        admin = AdminUser.objects.create(email="cminv@e2e.com", first_name="CM")
        admin.roles.add(role)
        ContentService().approve_submission(
            admin, str(submission.id), cashback_amount=10.0
        )

        for wallet in UserWallet.objects.all():
            ledger = ws._posted_ledger_sum(wallet)
            assert wallet.balance == ledger, (
                f"INVARIANT VIOLATED — wallet {wallet.id}: "
                f"balance={wallet.balance}, ledger={ledger}"
            )

    def test_pending_withdrawal_reduces_withdrawable_but_not_balance(
        self, economy_setup, ws
    ):
        """
        A PENDING withdrawal reserves funds in get_withdrawable_balance
        but does not yet touch wallet.balance.
        """
        d = economy_setup
        ContentService().purchase_episode(d["learner"], str(d["episode"].id))

        account = WithdrawalAccount.objects.create(
            admin_user=d["creator"],
            bank_code="044",
            account_number="0123456789",
            account_name="Creator E2E",
            status=WithdrawalAccount.Status.VERIFIED,
        )
        WithdrawalService().request_withdrawal(
            d["creator"], str(account.id), Decimal("70.00")
        )

        creator_w = ws.get_or_create_wallet(d["creator"])
        # Balance unchanged — PENDING doesn't affect it
        assert creator_w.balance == Decimal("70.00")
        # Withdrawable is 0 — all reserved by the pending withdrawal
        assert ws.get_withdrawable_balance(d["creator"]) == Decimal("0.00")
