from decimal import Decimal

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError

from skiflux.models import AdminUser
from skiflux.models.activity import ActivityLog
from skiflux.models.currency import CurrencyConfig
from skiflux.models.wallet import (
    SystemFinancialConfig,
    UserWallet,
)
from skiflux.repositories.payment_repository import PaymentTransactionRepository
from skiflux.repositories.user_repository import UserRepository
from skiflux.repositories.wallet_repository import WalletRepository
from skiflux.services.activity import ActivityService
from skiflux.services.content_service import ContentService
from skiflux.services.wallet_service import WalletService


class AdminWalletService:
    def __init__(self):
        self.wallet_service = WalletService()
        self.content_service = ContentService()
        self.payment_repo = PaymentTransactionRepository()
        self.wallet_repo = WalletRepository()
        self.user_repo = UserRepository()

    def get_financial_config(self) -> SystemFinancialConfig:
        return SystemFinancialConfig.get_config()

    def update_financial_config(
        self,
        admin: AdminUser,
        creator_share: Decimal = None,
        max_cashback: Decimal = None,
        project_task_cashback: Decimal = None,
        assessment_task_cashback: Decimal = None,
        episode_purchase_price: Decimal = None,
        default_currency: str = None,
        registration_bonus: Decimal = None,
        max_manual_adjustment: Decimal = None,
        enabled_topup_gateways: list = None,
        enabled_withdrawal_gateways: list = None,
        min_withdrawal_amount: Decimal = None,
        withdrawal_fee_percentage: Decimal = None,
        require_withdrawal_approval: bool = None,
        name_match_mode: str = None,
        max_withdrawal_accounts: int = None,
        pass_gateway_fees_to_customer: bool = None,
        max_saved_cards: int = None,
        card_verification_amount: Decimal = None,
        connect_payout_currency: str = None,
    ) -> SystemFinancialConfig:
        if not admin.is_super_admin:
            raise PermissionDenied(
                "Only super admins can update financial configurations."
            )

        config = SystemFinancialConfig.get_config()
        if creator_share is not None:
            if creator_share < Decimal("0.00") or creator_share > Decimal("100.00"):
                raise ValidationError("Percentage must be between 0.00 and 100.00.")
            config.creator_share_percentage = creator_share
        if max_cashback is not None:
            if max_cashback < Decimal("0.00"):
                raise ValidationError("Max cashback cap must be non-negative.")
            config.max_cashback_amount = max_cashback
        if project_task_cashback is not None:
            if project_task_cashback < Decimal("0.00"):
                raise ValidationError("Project task cashback must be non-negative.")
            config.project_task_cashback_amount = project_task_cashback
        if assessment_task_cashback is not None:
            if assessment_task_cashback < Decimal("0.00"):
                raise ValidationError("Assessment task cashback must be non-negative.")
            config.assessment_task_cashback_amount = assessment_task_cashback
        if episode_purchase_price is not None:
            if episode_purchase_price < Decimal("0.00"):
                raise ValidationError("Episode purchase price must be non-negative.")
            config.episode_purchase_price_skillcoins = episode_purchase_price

        if default_currency is not None:
            config.default_currency = default_currency
        if registration_bonus is not None:
            if registration_bonus < Decimal("0.00"):
                raise ValidationError("Registration bonus must be non-negative.")
            config.registration_bonus_skillcoins = registration_bonus
        if max_manual_adjustment is not None:
            if max_manual_adjustment <= Decimal("0.00"):
                raise ValidationError(
                    "Max manual adjustment must be greater than zero."
                )
            config.max_manual_adjustment_amount = max_manual_adjustment

        if enabled_topup_gateways is not None:
            if not isinstance(enabled_topup_gateways, list):
                raise ValidationError("enabled_topup_gateways must be a list.")
            known = {"flutterwave", "paystack", "stripe", "adyen"}
            # Normalise to lowercase before validation so 'Stripe' == 'stripe'
            enabled_topup_gateways = [g.lower() for g in enabled_topup_gateways]
            invalid = set(enabled_topup_gateways) - known
            if invalid:
                raise ValidationError(
                    f"Unknown gateway(s): {invalid}. Must be one of: {known}"
                )
            config.enabled_topup_gateways = enabled_topup_gateways

        if enabled_withdrawal_gateways is not None:
            if not isinstance(enabled_withdrawal_gateways, list):
                raise ValidationError("enabled_withdrawal_gateways must be a list.")
            known = {"flutterwave", "paystack", "stripe", "adyen"}
            # Normalise to lowercase before validation so 'Paystack' == 'paystack'
            enabled_withdrawal_gateways = [
                g.lower() for g in enabled_withdrawal_gateways
            ]
            invalid = set(enabled_withdrawal_gateways) - known
            if invalid:
                raise ValidationError(
                    f"Unknown gateway(s): {invalid}. Must be one of: {known}"
                )
            config.enabled_withdrawal_gateways = enabled_withdrawal_gateways

        if min_withdrawal_amount is not None:
            if min_withdrawal_amount < Decimal("0.00"):
                raise ValidationError("Minimum withdrawal amount must be non-negative.")
            config.min_withdrawal_amount = min_withdrawal_amount

        if withdrawal_fee_percentage is not None:
            if withdrawal_fee_percentage < Decimal(
                "0.00"
            ) or withdrawal_fee_percentage > Decimal("100.00"):
                raise ValidationError(
                    "Withdrawal fee percentage must be between 0.00 and 100.00."
                )
            config.withdrawal_fee_percentage = withdrawal_fee_percentage

        if require_withdrawal_approval is not None:
            config.require_withdrawal_approval = require_withdrawal_approval

        if name_match_mode is not None:
            if name_match_mode not in ["strict", "fuzzy", "relaxed"]:
                raise ValidationError(
                    "name_match_mode must be one of: strict, fuzzy, relaxed."
                )
            config.name_match_mode = name_match_mode

        if max_withdrawal_accounts is not None:
            if max_withdrawal_accounts < 1:
                raise ValidationError("Max withdrawal accounts must be at least 1.")
            config.max_withdrawal_accounts = max_withdrawal_accounts

        if pass_gateway_fees_to_customer is not None:
            config.pass_gateway_fees_to_customer = pass_gateway_fees_to_customer

        if max_saved_cards is not None:
            if max_saved_cards < 1:
                raise ValidationError("Max saved cards must be at least 1.")
            config.max_saved_cards = max_saved_cards

        if card_verification_amount is not None:
            if card_verification_amount < Decimal("0.00"):
                raise ValidationError("Card verification amount must be non-negative.")
            config.card_verification_amount = card_verification_amount

        if connect_payout_currency is not None:
            config.connect_payout_currency = connect_payout_currency.upper()

        config.updated_by = admin
        config.save()
        ActivityService.log_activity(
            action_type=ActivityLog.ActionType.FINANCIAL_CONFIG_UPDATED,
            description="System financial configuration was updated.",
            actor=admin,
            metadata={
                "creator_share_percentage": str(config.creator_share_percentage),
                "max_cashback_amount": str(config.max_cashback_amount),
                "project_task_cashback_amount": str(
                    config.project_task_cashback_amount
                ),
                "assessment_task_cashback_amount": str(
                    config.assessment_task_cashback_amount
                ),
                "episode_purchase_price_skillcoins": str(
                    config.episode_purchase_price_skillcoins
                ),
                "default_currency": config.default_currency,
                "registration_bonus_skillcoins": str(
                    config.registration_bonus_skillcoins
                ),
                "max_manual_adjustment_amount": str(
                    config.max_manual_adjustment_amount
                ),
                "max_withdrawal_accounts": config.max_withdrawal_accounts,
            },
        )
        return config

    def create_or_update_currency(
        self,
        admin: AdminUser,
        currency_code: str,
        currency_name: str,
        currency_symbol: str,
        skillcoin_rate: Decimal,
        is_active: bool = True,
        supported_gateways: list = None,
        country_code: str = "",
    ) -> CurrencyConfig:
        if not admin.is_super_admin:
            raise PermissionDenied("Only super admins can manage currencies.")

        if skillcoin_rate <= Decimal("0.00"):
            raise ValidationError("Skillcoin rate must be greater than zero.")

        currency, created = self.payment_repo.update_or_create_currency(
            currency_code=currency_code.upper(),
            defaults={
                "currency_name": currency_name,
                "currency_symbol": currency_symbol,
                "skillcoin_rate": skillcoin_rate,
                "is_active": is_active,
                "supported_gateways": supported_gateways or [],
                "country_code": country_code.upper(),
            },
        )
        return currency

    def list_currencies(self) -> list:
        return self.payment_repo.get_all_currencies()

    def get_gateway_fee_configs(self):
        from skiflux.models.wallet import GatewayFeeConfig

        return GatewayFeeConfig.objects.all().order_by(
            "gateway_name",
            "currency_code",
        )

    def create_or_update_gateway_fee_config(
        self,
        admin: AdminUser,
        data: dict,
    ):
        if not admin.is_super_admin:
            raise PermissionDenied("Only super admins can manage gateway fees.")

        from skiflux.models.wallet import GatewayFeeConfig

        gateway_name = data.get("gateway_name")
        currency_code = data.get("currency_code")

        if not gateway_name or not currency_code:
            raise ValidationError("Gateway name and currency code are required.")

        config, created = GatewayFeeConfig.objects.get_or_create(
            gateway_name=gateway_name.lower(),
            currency_code=currency_code.upper(),
        )

        # Validated fields only — explicitly assign each one to prevent
        # arbitrary mass-assignment and enforce bounds.
        _PERCENTAGE_FIELDS = ("fee_percentage", "vat_percentage")
        _DECIMAL_FIELDS = ("flat_fee", "flat_fee_threshold", "vat_flat", "cap_amount")

        for field in _PERCENTAGE_FIELDS:
            if field in data:
                val = data[field]
                if val is not None and (val < 0 or val > 100):
                    raise ValidationError(f"{field} must be between 0 and 100.")
                if field in data:
                    setattr(config, field, val)

        for field in _DECIMAL_FIELDS:
            if field in data:
                val = data[field]
                if val is not None and val < 0:
                    raise ValidationError(f"{field} must be non-negative.")
                setattr(config, field, val)

        config.updated_by = admin
        config.save()
        return config

    def delete_gateway_fee_config(self, admin: AdminUser, config_id: int):
        if not admin.is_super_admin:
            raise PermissionDenied("Only super admins can manage gateway fees.")

        from skiflux.models.wallet import GatewayFeeConfig

        try:
            config = GatewayFeeConfig.objects.get(id=config_id)
            config.delete()
        except GatewayFeeConfig.DoesNotExist:
            raise ValidationError("Gateway fee configuration not found.")

    def audit_global_ledger(self, search_query: str = ""):
        txs = self.wallet_repo.get_all_transactions()
        if search_query:
            txs = txs.filter(
                Q(wallet__user__email__icontains=search_query)
                | Q(wallet__admin_user__email__icontains=search_query)
                | Q(wallet__user__first_name__icontains=search_query)
                | Q(wallet__user__last_name__icontains=search_query)
                | Q(description__icontains=search_query)
                | Q(transaction_type__iexact=search_query)
            )
        return txs

    def manual_adjustment(
        self,
        admin: AdminUser,
        email: str,
        amount_str: str,
        is_credit: bool,
        description: str,
    ) -> UserWallet:
        if not email or not description:
            raise ValidationError(
                "Fields 'email', 'amount', 'is_credit', and 'description' are required."
            )
        user = self.user_repo.get_by_email(email)
        if not user:
            raise ValidationError(f"User with email '{email}' not found.")

        try:
            amount = Decimal(str(amount_str))
        except Exception:
            raise ValidationError("Invalid amount value format.")

        return self.wallet_service.manual_admin_adjustment(
            admin=admin,
            user=user,
            amount=amount,
            is_credit=is_credit,
            description=description,
        )

    def toggle_lock(
        self,
        admin: AdminUser,
        email: str,
        locked: bool,
    ) -> UserWallet:
        if not email or locked is None:
            raise ValidationError("Fields 'email' and 'locked' (boolean) are required.")
        user = self.user_repo.get_by_email(email)
        if not user:
            raise ValidationError(f"User with email '{email}' not found.")

        return self.wallet_service.toggle_wallet_lock(
            admin=admin, user=user, locked=bool(locked)
        )

    def issue_refund(self, admin: AdminUser, purchase_id: str) -> dict:
        if not purchase_id:
            raise ValidationError("Field 'purchase_id' is required.")
        return self.content_service.refund_episode_purchase(
            admin=admin, purchase_id=purchase_id
        )

    def verify_wallet_integrity(self, email: str) -> dict:
        if not email:
            raise ValidationError("Field 'email' is required.")
        user = self.user_repo.get_by_email(email)
        if not user:
            raise ValidationError(f"User with email '{email}' not found.")

        return self.wallet_service.audit_wallet_integrity(user)

    def get_platform_wallet_summary(self) -> dict:
        wallet = self.wallet_service.get_platform_wallet()
        ledger_sum = self.wallet_service._posted_ledger_sum(wallet)
        return {
            "wallet_id": str(wallet.id),
            "balance": str(wallet.balance),
            "ledger_sum": str(ledger_sum),
            "is_valid": wallet.balance == ledger_sum,
            "is_locked": wallet.is_locked,
        }
