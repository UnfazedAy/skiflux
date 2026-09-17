from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.exceptions import ValidationError

from skiflux.models import User
from skiflux.models.wallet import (
    SkillcoinTransaction,
    SystemFinancialConfig,
    WithdrawalAccount,
    WithdrawalHold,
    WithdrawalRequest,
)
from skiflux.services.wallet_service import WalletService
from skiflux.services.withdrawal_service import WithdrawalService


@pytest.fixture
def withdrawal_service():
    return WithdrawalService()


@pytest.fixture
def test_user(db):
    user = User.objects.create(email="john.doe@test.com", password="pwd")
    user.first_name = "John"
    user.last_name = "Doe"
    user.save()
    return user


@pytest.mark.django_db
class TestWithdrawalService:
    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_add_withdrawal_account_fuzzy_match(
        self, mock_resolve, withdrawal_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.name_match_mode = "relaxed"
        config.save()

        # The profile name is "John Doe", bank returns "John Doe Smith"
        mock_resolve.return_value = MagicMock(account_name="John Doe Smith")

        account = withdrawal_service.add_withdrawal_account(
            owner=test_user,
            bank_code="044",
            account_number="1234567890",
            gateway_name="flutterwave",
            bank_name="Access Bank",
        )

        assert account.status == WithdrawalAccount.Status.VERIFIED
        assert account.bank_name == "Access Bank"
        assert account.gateway_name == "flutterwave"

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.get_banks")
    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_add_withdrawal_account_resolves_bank_name_from_gateway(
        self, mock_resolve, mock_banks, withdrawal_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.name_match_mode = "relaxed"
        config.save()
        mock_resolve.return_value = MagicMock(account_name="John Doe")
        mock_banks.return_value = [
            {"code": "044", "name": "Access Bank"},
            {"code": "058", "name": "Guaranty Trust Bank"},
        ]

        account = withdrawal_service.add_withdrawal_account(
            owner=test_user,
            bank_code="044",
            account_number="1234567890",
            gateway_name="flutterwave",
        )

        assert account.bank_name == "Access Bank"
        assert account.bank_name != "flutterwave"

    def test_fuzzy_match_accepts_extra_middle_name(self, withdrawal_service):
        """Bank often returns a middle name the profile does not have."""
        assert withdrawal_service._verify_name_match(
            "Eniola Soniyi", "ENIOLA RACHEAL SONIYI", "fuzzy"
        )
        # Still reject totally unrelated names
        assert not withdrawal_service._verify_name_match(
            "Eniola Soniyi", "CHINEDU OKAFOR", "fuzzy"
        )

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_add_withdrawal_account_rejection(
        self, mock_resolve, withdrawal_service, test_user
    ):
        mock_resolve.return_value = MagicMock(account_name="Alice Bob")

        with pytest.raises(ValidationError, match="Account name .* does not match"):
            withdrawal_service.add_withdrawal_account(
                owner=test_user,
                bank_code="044",
                account_number="1234567890",
                gateway_name="flutterwave",
            )

    @pytest.mark.django_db
    def test_request_withdrawal(self, withdrawal_service, test_user):
        ws = WalletService()
        ws.credit_wallet(
            owner=test_user,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Initial",
        )

        config = SystemFinancialConfig.get_config()
        config.withdrawal_fee_percentage = Decimal("2.00")  # 2% fee
        config.require_withdrawal_approval = True
        config.min_withdrawal_amount = Decimal("100.00")
        config.save()

        account = WithdrawalAccount.objects.create(
            user=test_user,
            bank_code="044",
            account_number="1234",
            account_name="John Doe",
            status=WithdrawalAccount.Status.VERIFIED,
        )

        request = withdrawal_service.request_withdrawal(
            test_user, str(account.id), Decimal("500.00")
        )

        # Verification - aligned with WithdrawalHold reservation design
        assert request.amount == Decimal("500.00")
        assert request.fee == Decimal("10.00")  # 2% of 500
        assert request.net_amount == Decimal("490.00")
        assert request.status == WithdrawalRequest.Status.PENDING

        # No ledger transactions are created at request time.
        # The WithdrawalHold is the reservation mechanism.
        assert SkillcoinTransaction.objects.filter(reference_id=request.id).count() == 0

        hold = WithdrawalHold.objects.get(withdrawal_request=request)
        assert hold.status == WithdrawalHold.Status.ACTIVE
        assert hold.amount == Decimal("500.00")

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.initiate_transfer")
    def test_request_withdrawal_auto_processes_when_approval_not_required(
        self, mock_transfer, withdrawal_service, test_user
    ):
        ws = WalletService()
        ws.credit_wallet(
            owner=test_user,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Initial",
        )

        config = SystemFinancialConfig.get_config()
        config.enabled_withdrawal_gateways = ["flutterwave"]
        config.require_withdrawal_approval = False
        config.min_withdrawal_amount = Decimal("100.00")
        config.save()

        account = WithdrawalAccount.objects.create(
            user=test_user,
            bank_code="044",
            account_number="1234567890",
            account_name="John Doe",
            gateway_name="flutterwave",
            status=WithdrawalAccount.Status.VERIFIED,
        )

        mock_transfer.return_value = MagicMock(
            transfer_reference="FLW-AUTO-001",
            status="successful",
            raw_response={},
        )

        request = withdrawal_service.request_withdrawal(
            test_user, str(account.id), Decimal("500.00")
        )

        mock_transfer.assert_called_once()
        assert request.status == WithdrawalRequest.Status.COMPLETED
        assert request.gateway_name == "flutterwave"

    @patch("skiflux.gateways.paystack.PaystackGateway.initiate_transfer")
    def test_failed_auto_process_releases_hold(
        self, mock_transfer, withdrawal_service, test_user
    ):
        ws = WalletService()
        ws.credit_wallet(
            owner=test_user,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Initial",
        )

        config = SystemFinancialConfig.get_config()
        config.enabled_withdrawal_gateways = ["paystack"]
        config.require_withdrawal_approval = False
        config.min_withdrawal_amount = Decimal("100.00")
        config.save()

        account = WithdrawalAccount.objects.create(
            user=test_user,
            bank_code="044",
            account_number="1234567890",
            account_name="John Doe",
            gateway_name="paystack",
            status=WithdrawalAccount.Status.VERIFIED,
        )
        mock_transfer.side_effect = ValidationError(
            "You cannot initiate third party payouts as a starter business"
        )

        request = withdrawal_service.request_withdrawal(
            test_user, str(account.id), Decimal("500.00")
        )

        assert request.status == WithdrawalRequest.Status.FAILED
        hold = WithdrawalHold.objects.get(withdrawal_request=request)
        assert hold.status == WithdrawalHold.Status.RELEASED
        assert ws.get_withdrawable_balance(test_user) == Decimal("1000.00")

    @patch("skiflux.gateways.stripe_gateway.StripeGateway.create_onboarding_link")
    @patch("skiflux.gateways.stripe_gateway.StripeGateway.create_connect_account")
    def test_start_connect_onboarding_creates_pending_account(
        self, mock_create_acct, mock_link, withdrawal_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.enabled_withdrawal_gateways = ["paystack", "stripe"]
        config.save()

        mock_create_acct.return_value = "acct_test123"
        mock_link.return_value = "https://connect.stripe.com/setup/x"

        result = withdrawal_service.start_connect_onboarding(test_user)

        assert result["onboarding_url"] == "https://connect.stripe.com/setup/x"
        account = WithdrawalAccount.objects.get(user=test_user)
        assert (
            account.destination_type == WithdrawalAccount.DestinationType.STRIPE_CONNECT
        )
        assert account.stripe_account_id == "acct_test123"
        assert account.status == WithdrawalAccount.Status.PENDING

        # Calling again resumes the same account instead of creating a new one
        withdrawal_service.start_connect_onboarding(test_user)
        assert WithdrawalAccount.objects.filter(user=test_user).count() == 1
        assert mock_create_acct.call_count == 1

    @patch("skiflux.gateways.stripe_gateway.StripeGateway.get_connect_account_status")
    def test_refresh_connect_status_verifies_account(
        self, mock_status, withdrawal_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.enabled_withdrawal_gateways = ["stripe"]
        config.save()

        account = WithdrawalAccount.objects.create(
            user=test_user,
            destination_type=WithdrawalAccount.DestinationType.STRIPE_CONNECT,
            stripe_account_id="acct_test123",
            account_name="John Doe",
            status=WithdrawalAccount.Status.PENDING,
        )
        mock_status.return_value = {
            "payouts_enabled": True,
            "details_submitted": True,
            "currently_due": [],
        }

        result = withdrawal_service.refresh_connect_status(test_user)

        account.refresh_from_db()
        assert account.status == WithdrawalAccount.Status.VERIFIED
        assert result["payouts_enabled"] is True
        assert result["next_action"] is None

    @patch("skiflux.gateways.stripe_gateway.StripeGateway.initiate_connect_payout")
    def test_process_withdrawal_routes_connect_with_conversion(
        self, mock_payout, withdrawal_service, test_user
    ):
        from skiflux.models.currency import CurrencyConfig

        ws = WalletService()
        ws.credit_wallet(
            owner=test_user,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Initial",
        )

        config = SystemFinancialConfig.get_config()
        config.enabled_withdrawal_gateways = ["stripe"]
        config.withdrawal_fee_percentage = Decimal("2.00")
        config.min_withdrawal_amount = Decimal("100.00")
        config.connect_payout_currency = "USD"
        config.save()
        CurrencyConfig.objects.create(
            currency_code="USD",
            currency_name="US Dollar",
            currency_symbol="$",
            skillcoin_rate=Decimal("0.1000"),  # 1 Skillcoin = $0.10
            is_active=True,
            supported_gateways=["stripe"],
        )

        account = WithdrawalAccount.objects.create(
            user=test_user,
            destination_type=WithdrawalAccount.DestinationType.STRIPE_CONNECT,
            stripe_account_id="acct_test123",
            account_name="John Doe",
            status=WithdrawalAccount.Status.VERIFIED,
        )
        request = withdrawal_service.request_withdrawal(
            test_user, str(account.id), Decimal("500.00")
        )

        mock_payout.return_value = MagicMock(
            transfer_reference="tr_123",
            status="success",
            raw_response={"id": "tr_123"},
        )

        processed = withdrawal_service.process_withdrawal(
            admin=None, request_id=str(request.id), gateway_name="stripe"
        )

        # net 490 Skillcoins * 0.10 = $49.00
        assert mock_payout.call_args.kwargs["amount"] == Decimal("49.00")
        assert mock_payout.call_args.kwargs["currency"] == "USD"
        assert mock_payout.call_args.kwargs["account_id"] == "acct_test123"
        assert processed.gateway_reference == "tr_123"

        # A successful transfer completes the request inline (transition
        # from PROCESSING) and converts the hold to real ledger entries.
        assert processed.status == WithdrawalRequest.Status.COMPLETED
        hold = WithdrawalHold.objects.get(withdrawal_request=processed)
        assert hold.status == WithdrawalHold.Status.CONVERTED

    def test_mark_completed_from_processing_is_idempotent(
        self, withdrawal_service, test_user
    ):
        """A request already in PROCESSING (e.g. completed later via a
        transfer webhook) must complete exactly once."""
        ws = WalletService()
        ws.credit_wallet(
            owner=test_user,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Initial",
        )
        config = SystemFinancialConfig.get_config()
        config.min_withdrawal_amount = Decimal("100.00")
        config.save()

        account = WithdrawalAccount.objects.create(
            user=test_user,
            bank_code="044",
            account_number="1234567890",
            account_name="John Doe",
            status=WithdrawalAccount.Status.VERIFIED,
        )
        request = withdrawal_service.request_withdrawal(
            test_user, str(account.id), Decimal("500.00")
        )
        WithdrawalRequest.objects.filter(id=request.id).update(
            status=WithdrawalRequest.Status.PROCESSING
        )

        completed = withdrawal_service.mark_withdrawal_completed(str(request.id))
        assert completed.status == WithdrawalRequest.Status.COMPLETED
        hold = WithdrawalHold.objects.get(withdrawal_request=request)
        assert hold.status == WithdrawalHold.Status.CONVERTED

        # Second call is a no-op: still exactly one WITHDRAWAL ledger entry
        withdrawal_service.mark_withdrawal_completed(str(request.id))
        count = SkillcoinTransaction.objects.filter(
            reference_id=request.id,
            transaction_type=SkillcoinTransaction.Type.WITHDRAWAL,
            status=SkillcoinTransaction.Status.POSTED,
        ).count()
        assert count == 1

    def test_process_withdrawal_gateway_destination_mismatch(
        self, withdrawal_service, test_user
    ):
        ws = WalletService()
        ws.credit_wallet(
            owner=test_user,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Initial",
        )
        config = SystemFinancialConfig.get_config()
        config.enabled_withdrawal_gateways = ["paystack", "stripe"]
        config.min_withdrawal_amount = Decimal("100.00")
        config.save()

        bank_account = WithdrawalAccount.objects.create(
            user=test_user,
            bank_code="044",
            account_number="1234567890",
            account_name="John Doe",
            status=WithdrawalAccount.Status.VERIFIED,
        )
        request = withdrawal_service.request_withdrawal(
            test_user, str(bank_account.id), Decimal("500.00")
        )

        with pytest.raises(
            ValidationError, match="Stripe can only process Stripe Connect"
        ):
            withdrawal_service.process_withdrawal(
                admin=None, request_id=str(request.id), gateway_name="stripe"
            )

        # Request untouched — still pending, processable via the right gateway
        request.refresh_from_db()
        assert request.status == WithdrawalRequest.Status.PENDING

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_admin_user_can_add_account_and_request_withdrawal(
        self, mock_resolve, withdrawal_service
    ):
        from skiflux.models import AdminUser

        admin_owner = AdminUser.objects.create(
            email="creator@test.com",
            first_name="Jane",
            last_name="Creator",
        )
        WalletService().credit_wallet(
            owner=admin_owner,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.CREATOR_REVENUE,
            description="Earnings",
        )
        config = SystemFinancialConfig.get_config()
        config.name_match_mode = "relaxed"
        config.min_withdrawal_amount = Decimal("100.00")
        config.save()

        mock_resolve.return_value = MagicMock(account_name="Jane Creator")

        account = withdrawal_service.add_withdrawal_account(
            owner=admin_owner,
            bank_code="044",
            account_number="1234567890",
            gateway_name="flutterwave",
        )
        assert account.admin_user == admin_owner
        assert account.user is None

        request = withdrawal_service.request_withdrawal(
            admin_owner, str(account.id), Decimal("500.00")
        )
        assert request.status == WithdrawalRequest.Status.PENDING
        assert request.wallet.admin_user == admin_owner

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_add_withdrawal_account_respects_max_from_config(
        self, mock_resolve, withdrawal_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.max_withdrawal_accounts = 1
        config.save()

        mock_resolve.return_value = MagicMock(account_name="John Doe")

        # First add should succeed
        acc1 = withdrawal_service.add_withdrawal_account(
            owner=test_user,
            bank_code="044",
            account_number="1234567890",
            gateway_name="flutterwave",
        )
        assert acc1 is not None

        # Second should fail due to limit
        with pytest.raises(
            ValidationError, match="Maximum of 1 withdrawal accounts allowed"
        ):
            withdrawal_service.add_withdrawal_account(
                owner=test_user,
                bank_code="044",
                account_number="0987654321",
                gateway_name="flutterwave",
            )

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_remove_withdrawal_account(
        self, mock_resolve, withdrawal_service, test_user
    ):
        mock_resolve.return_value = MagicMock(account_name="John Doe")

        account = withdrawal_service.add_withdrawal_account(
            owner=test_user,
            bank_code="044",
            account_number="1234567890",
            gateway_name="flutterwave",
        )

        withdrawal_service.remove_withdrawal_account(test_user, str(account.id))

        account.refresh_from_db()
        assert account.is_active is False
        assert account.is_default is False
        assert (
            WithdrawalAccount.objects.filter(user=test_user, is_active=True).count()
            == 0
        )

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_remove_withdrawal_account_blocked_with_pending_request(
        self, mock_resolve, withdrawal_service, test_user
    ):
        ws = WalletService()
        ws.credit_wallet(
            owner=test_user,
            amount=Decimal("1000.00"),
            tx_type=SkillcoinTransaction.Type.TOPUP,
            description="Initial",
        )
        config = SystemFinancialConfig.get_config()
        config.min_withdrawal_amount = Decimal("100.00")
        config.require_withdrawal_approval = True
        config.save()

        mock_resolve.return_value = MagicMock(account_name="John Doe")
        account = withdrawal_service.add_withdrawal_account(
            owner=test_user,
            bank_code="044",
            account_number="1234567890",
            gateway_name="flutterwave",
        )
        withdrawal_service.request_withdrawal(
            test_user, str(account.id), Decimal("500.00")
        )

        with pytest.raises(ValidationError, match="pending or processing"):
            withdrawal_service.remove_withdrawal_account(test_user, str(account.id))

    @patch("skiflux.gateways.flutterwave.FlutterwaveGateway.resolve_bank_account")
    def test_remove_withdrawal_account_frees_slot(
        self, mock_resolve, withdrawal_service, test_user
    ):
        config = SystemFinancialConfig.get_config()
        config.max_withdrawal_accounts = 1
        config.save()
        mock_resolve.return_value = MagicMock(account_name="John Doe")

        account = withdrawal_service.add_withdrawal_account(
            owner=test_user,
            bank_code="044",
            account_number="1234567890",
            gateway_name="flutterwave",
        )
        withdrawal_service.remove_withdrawal_account(test_user, str(account.id))

        replacement = withdrawal_service.add_withdrawal_account(
            owner=test_user,
            bank_code="044",
            account_number="0987654321",
            gateway_name="flutterwave",
        )
        assert replacement.is_active is True
        assert replacement.id != account.id
