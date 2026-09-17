from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from skiflux.models.wallet import WithdrawalRequest
from skiflux.serializers.wallet import (
    AdminPaymentTransactionSerializer,
    CurrencyConfigCreateSerializer,
    CurrencyConfigSerializer,
    GatewayFeeConfigSerializer,
    IssueRefundSerializer,
    ManualAdjustmentSerializer,
    ProcessWithdrawalSerializer,
    RejectWithdrawalSerializer,
    SystemFinancialConfigSerializer,
    ToggleLockSerializer,
    UserWalletSerializer,
    VerifyIntegritySerializer,
    WalletAuditSerializer,
    WithdrawalRequestSerializer,
    serialize_financial_config,
)
from skiflux.services.admin_wallet_service import AdminWalletService
from skiflux.services.withdrawal_service import WithdrawalService
from skiflux.utils import AdminJWTAuthentication, APIResponse
from skiflux.utils.permissions import (
    HasEconomyManagePermission,
    HasEconomyViewPermission,
    IsSuperAdmin,
)


class AdminLedgerPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = "limit"
    max_page_size = 100


class AdminLedgerViewSet(viewsets.ViewSet):
    """Admin finance: ledger audit, adjustments, withdrawal processing."""

    authentication_classes = [AdminJWTAuthentication]
    serializer_class = WalletAuditSerializer

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.admin_wallet_service = AdminWalletService()

    def get_permissions(self):
        if self.action == "manage_financial_config":
            if self.request.method == "PATCH":
                return [IsAuthenticated(), IsSuperAdmin()]
            return [IsAuthenticated(), HasEconomyViewPermission()]
        if self.action in [
            "manual_adjustment",
            "toggle_lock",
            "issue_refund",
            "verify_wallet_integrity",
            "process_withdrawal",
            "reject_withdrawal",
        ]:
            return [IsAuthenticated(), HasEconomyManagePermission()]
        return [IsAuthenticated(), HasEconomyViewPermission()]

    @extend_schema(
        summary="Audit Global Ledger",
        description="Inspect all platform Skillcoin transaction events, "
        "filterable by email/search query.",
        parameters=[
            OpenApiParameter(
                "search",
                str,
                description="Search by email, name, description or transaction type",
            ),
            OpenApiParameter("limit", int, description="Page size limit"),
            OpenApiParameter("page", int, description="Page index"),
        ],
        responses={200: WalletAuditSerializer(many=True)},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["GET"], url_path="ledger-audit")
    def audit_global_ledger(self, request):
        search_query = request.query_params.get("search", "").strip()
        txs = self.admin_wallet_service.audit_global_ledger(search_query)

        paginator = AdminLedgerPagination()
        page = paginator.paginate_queryset(txs, request)
        serializer = WalletAuditSerializer(page, many=True)

        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Global system audit log retrieved.",
            data=data,
        )

    @extend_schema(
        summary="Adjust User Balance Manually",
        description="Adjust (credit or debit) a user's "
        "wallet with an audit-logged reason.",
        request=ManualAdjustmentSerializer,
        responses={200: UserWalletSerializer},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["POST"], url_path="manual-adjustment")
    def manual_adjustment(self, request):
        serializer = ManualAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        wallet = self.admin_wallet_service.manual_adjustment(
            admin=request.user,
            email=serializer.validated_data["email"],
            amount_str=str(serializer.validated_data["amount"]),
            is_credit=serializer.validated_data["is_credit"],
            description=serializer.validated_data["description"],
        )
        return APIResponse(
            status="success",
            status_code=200,
            message=f"Successfully adjusted balance for user '{serializer.validated_data['email']}'",  # noqa: E501
            data=UserWalletSerializer(wallet).data,
        )

    @extend_schema(
        summary="Toggle Wallet Suspension",
        description="Lock or Unlock a user's wallet to freeze all balance changes.",
        request=ToggleLockSerializer,
        responses={200: UserWalletSerializer},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["POST"], url_path="toggle-lock")
    def toggle_lock(self, request):
        serializer = ToggleLockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        wallet = self.admin_wallet_service.toggle_lock(
            admin=request.user,
            email=serializer.validated_data["email"],
            locked=serializer.validated_data["locked"],
        )
        action_word = "locked" if wallet.is_locked else "unlocked"
        return APIResponse(
            status="success",
            status_code=200,
            message=f"Wallet for user '{serializer.validated_data['email']}' has been successfully {action_word}.",  # noqa: E501
            data=UserWalletSerializer(wallet).data,
        )

    @extend_schema(
        summary="Issue Administrative Purchase Reversal & Refund",
        description="Revokes episode access and issues a full purchase "
        "price refund back to the user's wallet.",
        request=IssueRefundSerializer,
        responses={200: OpenApiResponse(description="Purchase successfully refunded.")},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["POST"], url_path="issue-refund")
    def issue_refund(self, request):
        serializer = IssueRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refund_data = self.admin_wallet_service.issue_refund(
            admin=request.user,
            purchase_id=str(serializer.validated_data["purchase_id"]),
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Episode purchase successfully refunded "
            "and streaming rights revoked.",
            data=refund_data,
        )

    @extend_schema(
        summary="Audit and Verify Wallet Integrity",
        description="Recalculates the user's transaction ledger "
        "history to check against the cached balance.",
        request=VerifyIntegritySerializer,
        responses={200: OpenApiResponse(description="Audit completed successfully.")},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["POST"], url_path="verify-integrity")
    def verify_wallet_integrity(self, request):
        serializer = VerifyIntegritySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        audit_results = self.admin_wallet_service.verify_wallet_integrity(
            email=serializer.validated_data["email"]
        )
        status_word = (
            "VALID" if audit_results["is_valid"] else "COMPROMISED (Wallet Frozen)"
        )
        return APIResponse(
            status="success",
            status_code=200,
            message=f"Integrity check complete. Status: {status_word}",
            data=audit_results,
        )

    @extend_schema(
        summary="Manage Platform Financial Configurations",
        description="Superadmin endpoints to fetch and update "
        "percentage revenue split, episode purchase price (Skillcoins), task cashbacks "
        "(project/assessment), cashback caps, and max withdrawal accounts.",
        request=SystemFinancialConfigSerializer,
        responses={200: SystemFinancialConfigSerializer},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["GET", "PATCH"], url_path="financial-config")
    def manage_financial_config(self, request):
        if request.method == "PATCH":
            serializer = SystemFinancialConfigSerializer(
                data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            config = self.admin_wallet_service.update_financial_config(
                admin=request.user,
                creator_share=serializer.validated_data.get("creator_share_percentage"),
                max_cashback=serializer.validated_data.get("max_cashback_amount"),
                project_task_cashback=serializer.validated_data.get(
                    "project_task_cashback_amount"
                ),
                assessment_task_cashback=serializer.validated_data.get(
                    "assessment_task_cashback_amount"
                ),
                episode_purchase_price=serializer.validated_data.get(
                    "episode_purchase_price_skillcoins"
                ),
                registration_bonus=serializer.validated_data.get(
                    "registration_bonus_skillcoins"
                ),
                max_manual_adjustment=serializer.validated_data.get(
                    "max_manual_adjustment_amount"
                ),
                enabled_topup_gateways=serializer.validated_data.get(
                    "enabled_topup_gateways"
                ),
                enabled_withdrawal_gateways=serializer.validated_data.get(
                    "enabled_withdrawal_gateways"
                ),
                min_withdrawal_amount=serializer.validated_data.get(
                    "min_withdrawal_amount"
                ),
                withdrawal_fee_percentage=serializer.validated_data.get(
                    "withdrawal_fee_percentage"
                ),
                require_withdrawal_approval=serializer.validated_data.get(
                    "require_withdrawal_approval"
                ),
                name_match_mode=serializer.validated_data.get("name_match_mode"),
                max_withdrawal_accounts=serializer.validated_data.get(
                    "max_withdrawal_accounts"
                ),
                pass_gateway_fees_to_customer=serializer.validated_data.get(
                    "pass_gateway_fees_to_customer"
                ),
                max_saved_cards=serializer.validated_data.get("max_saved_cards"),
                card_verification_amount=serializer.validated_data.get(
                    "card_verification_amount"
                ),
                connect_payout_currency=serializer.validated_data.get(
                    "connect_payout_currency"
                ),
            )
            return APIResponse(
                status="success",
                status_code=200,
                message="Financial parameters updated successfully.",
                data=serialize_financial_config(config),
            )

        config = self.admin_wallet_service.get_financial_config()
        return APIResponse(
            status="success",
            status_code=200,
            message="Financial configuration retrieved.",
            data=serialize_financial_config(config),
        )

    @extend_schema(
        summary="List All Withdrawal Requests",
        responses={200: WithdrawalRequestSerializer(many=True)},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/requests")
    def list_withdrawal_requests(self, request):
        reqs = WithdrawalRequest.objects.all().order_by("-created_at")
        paginator = AdminLedgerPagination()
        page = paginator.paginate_queryset(reqs, request)
        serializer = WithdrawalRequestSerializer(page, many=True)
        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Withdrawal requests fetched.",
            data=data,
        )

    @extend_schema(
        summary="Process Withdrawal Request",
        request=ProcessWithdrawalSerializer,
        responses={200: WithdrawalRequestSerializer},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["POST"], url_path="withdrawals/process")
    def process_withdrawal(self, request):
        serializer = ProcessWithdrawalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        withdrawal_service = WithdrawalService()
        req = withdrawal_service.process_withdrawal(
            admin=request.user,
            request_id=serializer.validated_data["request_id"],
            gateway_name=serializer.validated_data["gateway_name"],
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Withdrawal processing initiated.",
            data=WithdrawalRequestSerializer(req).data,
        )

    @extend_schema(
        summary="Reject Withdrawal Request",
        request=RejectWithdrawalSerializer,
        responses={200: WithdrawalRequestSerializer},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["POST"], url_path="withdrawals/reject")
    def reject_withdrawal(self, request):
        serializer = RejectWithdrawalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        withdrawal_service = WithdrawalService()
        req = withdrawal_service.reject_withdrawal(
            admin=request.user,
            request_id=serializer.validated_data["request_id"],
            reason=serializer.validated_data["reason"],
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Withdrawal request rejected.",
            data=WithdrawalRequestSerializer(req).data,
        )

    @extend_schema(
        summary="Platform Wallet Summary",
        description="Returns the platform revenue wallet balance and ledger integrity.",
        responses={200: OpenApiResponse(description="Platform wallet data.")},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["GET"], url_path="platform-wallet")
    def platform_wallet_summary(self, request):
        data = self.admin_wallet_service.get_platform_wallet_summary()
        return APIResponse(
            status="success",
            status_code=200,
            message="Platform wallet retrieved.",
            data=data,
        )

    @extend_schema(
        summary="Manage Currencies",
        description="List all currencies or create/update a new one.",
        request=CurrencyConfigCreateSerializer,
        responses={200: CurrencyConfigSerializer(many=True)},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["GET", "POST"], url_path="currencies")
    def manage_currencies(self, request):
        if request.method == "POST":
            serializer = CurrencyConfigCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            curr = self.admin_wallet_service.create_or_update_currency(
                admin=request.user,
                currency_code=serializer.validated_data["currency_code"],
                currency_name=serializer.validated_data["currency_name"],
                currency_symbol=serializer.validated_data["currency_symbol"],
                skillcoin_rate=serializer.validated_data["skillcoin_rate"],
                is_active=serializer.validated_data.get("is_active", True),
                supported_gateways=serializer.validated_data.get(
                    "supported_gateways", []
                ),
                country_code=serializer.validated_data.get("country_code", ""),
            )
            return APIResponse(
                status="success",
                status_code=201,
                message="Currency configured successfully.",
                data=CurrencyConfigSerializer(curr).data,
            )

        currencies = self.admin_wallet_service.list_currencies()
        return APIResponse(
            status="success",
            status_code=200,
            message="Currencies fetched.",
            data=CurrencyConfigSerializer(currencies, many=True).data,
        )

    @extend_schema(
        summary="List Payment Transactions",
        description="List all fiat top-up payment transactions. "
        "Filterable by status (initiated/pending/successful/failed/cancelled) "
        "and gateway.",
        parameters=[
            OpenApiParameter(
                "status",
                str,
                description="Filter by transaction status (e.g. successful, pending, failed)",  # noqa: E501
            ),
            OpenApiParameter(
                "gateway",
                str,
                description="Filter by gateway name (e.g. flutterwave, paystack)",
            ),
            OpenApiParameter(
                "email",
                str,
                description="Filter by user email (partial match)",
            ),
            OpenApiParameter("limit", int, description="Page size limit"),
            OpenApiParameter("page", int, description="Page index"),
        ],
        responses={200: AdminPaymentTransactionSerializer(many=True)},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["GET"], url_path="payment-transactions")
    def list_payment_transactions(self, request):
        from skiflux.models.wallet import PaymentTransaction

        qs = PaymentTransaction.objects.select_related("user", "admin_user").order_by(
            "-created_at"
        )

        status_filter = request.query_params.get("status", "").strip()
        gateway_filter = request.query_params.get("gateway", "").strip()
        email_filter = request.query_params.get("email", "").strip()

        if status_filter:
            qs = qs.filter(status=status_filter)
        if gateway_filter:
            qs = qs.filter(gateway=gateway_filter)
        if email_filter:
            qs = qs.filter(user__email__icontains=email_filter)

        paginator = AdminLedgerPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AdminPaymentTransactionSerializer(page, many=True)

        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Payment transactions fetched.",
            data=data,
        )

    @extend_schema(
        summary="List Gateway Fee Configurations",
        description="View all gateway fee configurations.",
        responses={200: GatewayFeeConfigSerializer(many=True)},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["GET"], url_path="gateway-fees")
    def get_gateway_fees(self, request):
        configs = self.admin_wallet_service.get_gateway_fee_configs()
        serializer = GatewayFeeConfigSerializer(configs, many=True)
        return APIResponse(
            status="success",
            status_code=200,
            message="Gateway fee configurations retrieved successfully.",
            data=serializer.data,
        )

    @extend_schema(
        summary="Create or Update Gateway Fee Configuration",
        description="Set fee rules for a specific gateway and currency combination.",
        request=GatewayFeeConfigSerializer,
        responses={200: GatewayFeeConfigSerializer},
        tags=["Admin › Economy"],
    )
    @action(detail=False, methods=["POST"], url_path="gateway-fees/update")
    def update_gateway_fees(self, request):
        serializer = GatewayFeeConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = self.admin_wallet_service.create_or_update_gateway_fee_config(
            admin=request.user, data=serializer.validated_data
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Gateway fee configuration updated successfully.",
            data=GatewayFeeConfigSerializer(config).data,
        )

    @extend_schema(
        summary="Delete Gateway Fee Configuration",
        description="Remove a specific gateway fee configuration.",
        responses={200: OpenApiResponse(description="Configuration deleted.")},
        tags=["Admin › Economy"],
    )
    @action(
        detail=False, methods=["DELETE"], url_path="gateway-fees/(?P<config_id>[^/.]+)"
    )
    def delete_gateway_fee(self, request, config_id=None):
        try:
            config_id_int = int(config_id)
        except (TypeError, ValueError):
            from rest_framework.exceptions import ValidationError as DRFValidationError

            raise DRFValidationError("config_id must be a valid integer.")
        self.admin_wallet_service.delete_gateway_fee_config(
            admin=request.user, config_id=config_id_int
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Gateway fee configuration deleted successfully.",
        )
