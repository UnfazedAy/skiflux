from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from skiflux.gateways.payment_channels import TOPUP_PAYMENT_METHOD_CHOICES
from skiflux.models import SkillcoinTransaction, UserWallet
from skiflux.models.currency import CurrencyConfig
from skiflux.models.wallet import (
    PaymentTransaction,
    SavedCard,
    WithdrawalAccount,
    WithdrawalRequest,
)


class SkillcoinTransactionSerializer(serializers.ModelSerializer):
    transaction_type_label = serializers.CharField(
        source="get_transaction_type_display", read_only=True
    )

    class Meta:
        model = SkillcoinTransaction
        fields = [
            "id",
            "amount",
            "transaction_type",
            "transaction_type_label",
            "status",
            "description",
            "reference_id",
            "created_at",
        ]


class UserWalletSerializer(serializers.ModelSerializer):
    withdrawable_balance = serializers.SerializerMethodField()

    class Meta:
        model = UserWallet
        fields = [
            "id",
            "balance",
            "bonus_balance",
            "withdrawable_balance",
            "is_locked",
            "is_platform_wallet",
            "updated_at",
        ]

    @extend_schema_field(serializers.FloatField())
    def get_withdrawable_balance(self, obj) -> float:
        from skiflux.services.wallet_service import WalletService

        return float(WalletService().get_withdrawable_balance_from_wallet(obj))


class WalletAuditSerializer(serializers.ModelSerializer):
    """Detailed audit view mapping transaction records to users and executing admins."""

    user_email = serializers.EmailField(source="wallet.user.email", read_only=True)
    user_name = serializers.SerializerMethodField()
    admin_email = serializers.EmailField(source="admin_user.email", read_only=True)

    class Meta:
        model = SkillcoinTransaction
        fields = [
            "id",
            "user_email",
            "user_name",
            "amount",
            "transaction_type",
            "status",
            "description",
            "reference_id",
            "admin_email",
            "created_at",
        ]

    def get_user_name(self, obj) -> str:
        if obj.wallet.user:
            u = obj.wallet.user
            return (
                f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name', '')}".strip()
                or getattr(u, "email", "")
            )
        admin = obj.wallet.admin_user
        if admin is None:
            return "Platform Wallet"
        return (
            f"{getattr(admin, 'first_name', '')} {getattr(admin, 'last_name', '')}".strip()  # noqa: E501
            or getattr(admin, "email", "")
        )


def serialize_financial_config(config) -> dict:
    return {
        "creator_share_percentage": config.creator_share_percentage,
        "max_cashback_amount": config.max_cashback_amount,
        "project_task_cashback_amount": config.project_task_cashback_amount,
        "assessment_task_cashback_amount": config.assessment_task_cashback_amount,
        "episode_purchase_price_skillcoins": config.episode_purchase_price_skillcoins,
        "default_currency": config.default_currency,
        "registration_bonus_skillcoins": config.registration_bonus_skillcoins,
        "max_manual_adjustment_amount": config.max_manual_adjustment_amount,
        "enabled_topup_gateways": config.enabled_topup_gateways,
        "enabled_withdrawal_gateways": config.enabled_withdrawal_gateways,
        "min_withdrawal_amount": config.min_withdrawal_amount,
        "withdrawal_fee_percentage": config.withdrawal_fee_percentage,
        "require_withdrawal_approval": config.require_withdrawal_approval,
        "name_match_mode": config.name_match_mode,
        "max_withdrawal_accounts": config.max_withdrawal_accounts,
        "max_saved_cards": config.max_saved_cards,
        "card_verification_amount": config.card_verification_amount,
        "connect_payout_currency": config.connect_payout_currency,
        "updated_at": config.updated_at,
        "updated_by_email": config.updated_by.email if config.updated_by else None,
        "pass_gateway_fees_to_customer": config.pass_gateway_fees_to_customer,
    }


class SystemFinancialConfigSerializer(serializers.Serializer):
    creator_share_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False
    )
    max_cashback_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    project_task_cashback_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    assessment_task_cashback_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    episode_purchase_price_skillcoins = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, min_value=0
    )

    default_currency = serializers.CharField(max_length=3, required=False)
    registration_bonus_skillcoins = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    max_manual_adjustment_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    enabled_topup_gateways = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    enabled_withdrawal_gateways = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    min_withdrawal_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    withdrawal_fee_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False
    )
    require_withdrawal_approval = serializers.BooleanField(
        allow_null=True, required=False
    )
    name_match_mode = serializers.ChoiceField(
        choices=["strict", "fuzzy", "relaxed"], required=False
    )
    max_withdrawal_accounts = serializers.IntegerField(required=False, min_value=1)
    max_saved_cards = serializers.IntegerField(required=False, min_value=1)
    card_verification_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    connect_payout_currency = serializers.CharField(max_length=3, required=False)
    updated_at = serializers.DateTimeField(read_only=True)
    updated_by_email = serializers.EmailField(
        source="updated_by.email", read_only=True, allow_null=True
    )
    pass_gateway_fees_to_customer = serializers.BooleanField(
        allow_null=True, required=False
    )


class GatewayFeeConfigSerializer(serializers.ModelSerializer):
    updated_by_email = serializers.EmailField(
        source="updated_by.email", read_only=True, allow_null=True
    )

    class Meta:
        from skiflux.models.wallet import GatewayFeeConfig

        model = GatewayFeeConfig
        fields = [
            "id",
            "gateway_name",
            "currency_code",
            "fee_percentage",
            "flat_fee",
            "flat_fee_threshold",
            "cap_amount",
            "vat_percentage",
            "vat_flat",
            "updated_at",
            "updated_by_email",
        ]
        read_only_fields = ["id", "updated_at", "updated_by_email"]


class ManualAdjustmentSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=True)
    is_credit = serializers.BooleanField(default=True)
    description = serializers.CharField(max_length=255, required=True)


class ToggleLockSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    locked = serializers.BooleanField(required=True)


class IssueRefundSerializer(serializers.Serializer):
    purchase_id = serializers.UUIDField(required=True)


class VerifyIntegritySerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class SavedCardSerializer(serializers.ModelSerializer):
    """Masked card view. The gateway token and customer code are never
    serialized."""

    masked_number = serializers.CharField(read_only=True)

    class Meta:
        model = SavedCard
        fields = [
            "id",
            "gateway_name",
            "card_brand",
            "masked_number",
            "last4",
            "exp_month",
            "exp_year",
            "bank_name",
            "card_type",
            "is_default",
            "created_at",
        ]


class AddCardSerializer(serializers.Serializer):
    gateway_name = serializers.CharField(required=True)
    redirect_url = serializers.URLField(
        required=False, allow_blank=True, allow_null=True
    )


class ChargeSavedCardSerializer(serializers.Serializer):
    saved_card_id = serializers.UUIDField(required=True)
    amount_fiat = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True
    )
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )


class ConnectOnboardSerializer(serializers.Serializer):
    return_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    refresh_url = serializers.URLField(
        required=False, allow_blank=True, allow_null=True
    )


class WithdrawalAccountSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = WithdrawalAccount
        fields = [
            "id",
            "destination_type",
            "gateway_name",
            "display_name",
            "bank_code",
            "bank_name",
            "account_number",
            "account_name",
            "status",
            "is_default",
            "created_at",
        ]


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    account = WithdrawalAccountSerializer(source="withdrawal_account", read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "amount",
            "fee",
            "net_amount",
            "status",
            "gateway_name",
            "failure_reason",
            "processed_at",
            "created_at",
            "account",
        ]


class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "amount_fiat",
            "amount_skillcoins",
            "currency",
            "gateway",
            "status",
            "tx_ref",
            "verified_at",
            "created_at",
        ]


class AdminPaymentTransactionSerializer(serializers.ModelSerializer):
    """Extended serializer for admin views with user identity info."""

    user_email = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "user_email",
            "amount_fiat",
            "currency",
            "amount_skillcoins",
            "gateway",
            "gateway_reference",
            "status",
            "tx_ref",
            "verified_at",
            "created_at",
        ]

    def get_user_email(self, obj) -> str:
        if obj.user_id:
            return obj.user.email
        if obj.admin_user_id:
            return obj.admin_user.email
        return ""


class TopupInitiateSerializer(serializers.Serializer):
    amount_fiat = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True
    )
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    gateway_name = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    redirect_url = serializers.URLField(
        required=False, allow_blank=True, allow_null=True
    )
    save_card = serializers.BooleanField(required=False, default=False)
    payment_method = serializers.ChoiceField(
        choices=TOPUP_PAYMENT_METHOD_CHOICES,
        required=False,
        default="all",
        help_text="Restrict hosted checkout: card, bank_transfer, or all (default).",
    )


class VerifyPaymentSerializer(serializers.Serializer):
    tx_ref = serializers.CharField(required=True)
    gateway_reference = serializers.CharField(required=False, allow_blank=True)


class WithdrawalAccountCreateSerializer(serializers.Serializer):
    bank_code = serializers.CharField(required=True)
    account_number = serializers.CharField(required=True)
    gateway_name = serializers.CharField(required=True)
    bank_name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional display name from the banks list. "
        "If omitted, the backend resolves it from the gateway by bank_code.",
    )


class WithdrawalRequestCreateSerializer(serializers.Serializer):
    account_id = serializers.UUIDField(required=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=True)


class ProcessWithdrawalSerializer(serializers.Serializer):
    request_id = serializers.UUIDField(required=True)
    gateway_name = serializers.CharField(required=True)


class RejectWithdrawalSerializer(serializers.Serializer):
    request_id = serializers.UUIDField(required=True)
    reason = serializers.CharField(required=True)


class WalletFinancialSummarySerializer(serializers.Serializer):
    """Serializer for the user's total earned, spent, and withdrawn stats."""

    total_earned = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    total_spent = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    total_withdrawn = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )


class CurrencyConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurrencyConfig
        fields = [
            "id",
            "currency_code",
            "currency_name",
            "currency_symbol",
            "skillcoin_rate",
            "is_active",
            "supported_gateways",
            "country_code",
            "created_at",
            "updated_at",
        ]


class CurrencyConfigCreateSerializer(serializers.Serializer):
    currency_code = serializers.CharField(max_length=3)
    currency_name = serializers.CharField(max_length=50)
    currency_symbol = serializers.CharField(max_length=5)
    skillcoin_rate = serializers.DecimalField(max_digits=12, decimal_places=4)
    is_active = serializers.BooleanField(default=True)
    supported_gateways = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    country_code = serializers.CharField(max_length=2, required=False, allow_blank=True)


class TransactionReportRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
    details = serializers.CharField(required=False, allow_blank=True, default="")


class TransactionReportResponseSerializer(serializers.Serializer):
    case_id = serializers.UUIDField()
    status = serializers.CharField()
    ticket_number = serializers.CharField(required=False, allow_null=True)


class WithdrawalMethodItemSerializer(serializers.Serializer):
    method = serializers.CharField()
    gateway = serializers.CharField()
    flow = serializers.CharField()
    label = serializers.CharField()


class WithdrawalMethodsResponseSerializer(serializers.Serializer):
    withdrawal_fee_percentage = serializers.CharField(
        help_text="Platform withdrawal fee percentage as a string decimal."
    )
    methods = WithdrawalMethodItemSerializer(many=True)
