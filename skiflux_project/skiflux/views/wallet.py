from drf_spectacular.utils import OpenApiResponse, extend_schema, OpenApiParameter
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from skiflux.gateways.registry import PaymentGatewayFactory
from skiflux.models.wallet import (
    SkillcoinTransaction,
    WithdrawalAccount,
    WithdrawalRequest,
)
from skiflux.serializers.wallet import (
    AddCardSerializer,
    ChargeSavedCardSerializer,
    ConnectOnboardSerializer,
    PaymentTransactionSerializer,
    SavedCardSerializer,
    SkillcoinTransactionSerializer,
    TopupInitiateSerializer,
    TransactionReportRequestSerializer,
    TransactionReportResponseSerializer,
    WithdrawalMethodsResponseSerializer,
    UserWalletSerializer,
    VerifyPaymentSerializer,
    WalletFinancialSummarySerializer,
    WithdrawalAccountCreateSerializer,
    WithdrawalAccountSerializer,
    WithdrawalRequestCreateSerializer,
    WithdrawalRequestSerializer,
)
from skiflux.services.card_service import CardService
from skiflux.services.payment_service import PaymentService
from skiflux.services.wallet_service import WalletService
from skiflux.services.withdrawal_service import WithdrawalService
from skiflux.utils import APIResponse
from skiflux.utils.auth import JWTAuthentication


class WalletPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = "page_size"
    max_page_size = 50


class UserWalletViewSet(viewsets.ViewSet):
    """User wallet: top-up, saved cards, withdrawals."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = UserWalletSerializer

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wallet_service = WalletService()
        self.payment_service = PaymentService()
        self.withdrawal_service = WithdrawalService()
        self.card_service = CardService()

    @extend_schema(
        summary="Fetch My Wallet Balance",
        description="Retrieves the calling user's current "
        "Skillcoin balance and suspension status.",
        responses={200: UserWalletSerializer},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="my-wallet")
    def retrieve_my_wallet(self, request):
        wallet = self.wallet_service.get_or_create_wallet(request.user)
        serializer = UserWalletSerializer(wallet)
        return APIResponse(
            status="success",
            status_code=200,
            message="Wallet balance fetched.",
            data=serializer.data,
        )

    @extend_schema(
        summary="List My Transaction History",
        description="Get a paginated feed of all Skillcoin transaction entries.",
        responses={200: SkillcoinTransactionSerializer(many=True)},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="my-transactions")
    def list_my_transactions(self, request):
        wallet = self.wallet_service.get_or_create_wallet(request.user)
        txs = SkillcoinTransaction.objects.filter(wallet=wallet).order_by("-created_at")

        paginator = WalletPagination()
        page = paginator.paginate_queryset(txs, request)

        serializer = SkillcoinTransactionSerializer(page, many=True)
        data = {
            "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "results": serializer.data,
        }
        return APIResponse(
            status="success",
            status_code=200,
            message="Transactions fetched.",
            data=data,
        )

    @extend_schema(
        summary="Initiate Wallet Top-up",
        request=TopupInitiateSerializer,
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="topup/initiate")
    def initiate_topup(self, request):
        serializer = TopupInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Accept idempotency key from body or the standard Idempotency-Key header
        idempotency_key = serializer.validated_data.get(
            "idempotency_key"
        ) or request.headers.get("Idempotency-Key")

        result = self.payment_service.initiate_topup(
            user=request.user,
            amount_fiat=serializer.validated_data["amount_fiat"],
            gateway_name=serializer.validated_data.get("gateway_name"),
            currency=serializer.validated_data.get("currency"),
            redirect_url=serializer.validated_data.get("redirect_url"),
            idempotency_key=idempotency_key,
            save_card=serializer.validated_data.get("save_card", False),
            payment_method=serializer.validated_data.get("payment_method", "all"),
        )
        return APIResponse(
            status="success", status_code=200, message="Top-up initiated.", data=result
        )

    @extend_schema(
        summary="List Top-up Methods",
        description="Active currencies and the gateways that support them. "
        "Drives the frontend's add-money screen with no hardcoding.",
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="topup/methods")
    def get_topup_methods(self, request):
        methods = self.payment_service.get_topup_methods()
        cards = SavedCardSerializer(
            self.card_service.list_cards(request.user), many=True
        ).data
        return APIResponse(
            status="success",
            status_code=200,
            message="Top-up methods fetched.",
            data={"currencies": methods, "saved_cards": cards},
        )

    @extend_schema(
        summary="Top-up With a Saved Card",
        description="One-tap top-up: charges a previously saved card token. "
        "No checkout redirect needed.",
        request=ChargeSavedCardSerializer,
        responses={200: PaymentTransactionSerializer},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="topup/charge-card")
    def charge_saved_card(self, request):
        serializer = ChargeSavedCardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        idempotency_key = serializer.validated_data.get(
            "idempotency_key"
        ) or request.headers.get("Idempotency-Key")

        tx = self.card_service.charge_saved_card_topup(
            owner=request.user,
            saved_card_id=str(serializer.validated_data["saved_card_id"]),
            amount_fiat=serializer.validated_data["amount_fiat"],
            currency=serializer.validated_data.get("currency") or None,
            idempotency_key=idempotency_key,
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Card charged and wallet credited.",
            data=PaymentTransactionSerializer(tx).data,
        )

    @extend_schema(
        summary="Add a Card",
        description="Start the save-card flow. Returns a checkout URL: "
        "Paystack charges a small verification amount (refunded to the card); "
        "Stripe uses a no-charge setup session. Only the token and "
        "masked details (brand, last 4) are ever stored.",
        request=AddCardSerializer,
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="cards/add")
    def add_card(self, request):
        serializer = AddCardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = self.card_service.initiate_add_card(
            owner=request.user,
            gateway_name=serializer.validated_data["gateway_name"],
            redirect_url=serializer.validated_data.get("redirect_url"),
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Card setup initiated.",
            data=result,
        )

    @extend_schema(
        summary="List My Saved Cards",
        responses={200: SavedCardSerializer(many=True)},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="cards")
    def list_cards(self, request):
        cards = self.card_service.list_cards(request.user)
        return APIResponse(
            status="success",
            status_code=200,
            message="Saved cards fetched.",
            data=SavedCardSerializer(cards, many=True).data,
        )

    @extend_schema(
        summary="Remove a Saved Card",
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=True, methods=["DELETE"], url_path="cards")
    def remove_card(self, request, pk=None):
        self.card_service.deactivate_card(request.user, pk)
        return APIResponse(
            status="success",
            status_code=200,
            message="Card removed.",
            data={"id": pk},
        )

    @extend_schema(
        summary="Set Default Saved Card",
        responses={200: SavedCardSerializer},
        tags=["User › Wallet"],
    )
    @action(detail=True, methods=["POST"], url_path="cards/set-default")
    def set_default_card(self, request, pk=None):
        card = self.card_service.set_default_card(request.user, pk)
        return APIResponse(
            status="success",
            status_code=200,
            message="Default card updated.",
            data=SavedCardSerializer(card).data,
        )

    @extend_schema(
        summary="Verify Top-up",
        request=VerifyPaymentSerializer,
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="topup/verify")
    def verify_topup(self, request):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tx = self.payment_service.verify_payment(
            tx_ref=serializer.validated_data["tx_ref"],
            gateway_reference=serializer.validated_data.get("gateway_reference"),
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Top-up verified.",
            data={"status": tx.status, "amount_skillcoins": tx.amount_skillcoins},
        )

    @extend_schema(
        summary="Get Supported Banks",
        parameters=[
            OpenApiParameter(
                name="gateway",
                description=(
                    "The name of the gateway to get banks for. Defaults to paystack."
                ),
                required=False,
                type=str,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=dict,
                description="List of supported banks for the selected gateway",
            )
        },
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/banks")
    def get_withdrawal_banks(self, request):
        gateway_name = request.query_params.get("gateway") or "paystack"
        gateway = PaymentGatewayFactory.get_gateway(gateway_name, purpose="withdrawal")
        banks = gateway.get_banks()
        return APIResponse(
            status="success", status_code=200, message="Banks fetched.", data=banks
        )

    @extend_schema(
        summary="List Withdrawal Methods",
        description="Enabled withdrawal methods for any account — no "
        "geography assumptions. The frontend switches on `flow`: "
        "`bank_form` renders the bank picker; `hosted_redirect` calls "
        "the Connect onboard endpoint and opens the returned URL. "
        "Includes `withdrawal_fee_percentage` for pre-submit confirmation UI.",
        responses={200: WithdrawalMethodsResponseSerializer},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/methods")
    def get_withdrawal_methods(self, request):
        methods = self.withdrawal_service.get_withdrawal_methods()
        return APIResponse(
            status="success",
            status_code=200,
            message="Withdrawal methods fetched.",
            data=methods,
        )

    @extend_schema(
        summary="Start Stripe Connect Withdrawal Setup",
        description="Returns a Stripe-hosted onboarding URL where the user "
        "attaches a bank account or debit card. Stripe handles KYC and "
        "storage; only the account id is kept here.",
        request=ConnectOnboardSerializer,
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="withdrawals/connect/onboard")
    def connect_onboard(self, request):
        serializer = ConnectOnboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = self.withdrawal_service.start_connect_onboarding(
            owner=request.user,
            return_url=serializer.validated_data.get("return_url"),
            refresh_url=serializer.validated_data.get("refresh_url"),
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Stripe onboarding link created.",
            data=result,
        )

    @extend_schema(
        summary="Check Stripe Connect Withdrawal Status",
        description="Call on return from Stripe onboarding. Verifies the "
        "withdrawal destination once payouts are enabled; otherwise "
        "returns a fresh onboarding link as `next_action`.",
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/connect/status")
    def connect_status(self, request):
        result = self.withdrawal_service.refresh_connect_status(owner=request.user)
        return APIResponse(
            status="success",
            status_code=200,
            message="Stripe withdrawal status fetched.",
            data=result,
        )

    @extend_schema(
        summary="Add Withdrawal Account",
        request=WithdrawalAccountCreateSerializer,
        responses={201: WithdrawalAccountSerializer},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="withdrawals/accounts")
    def add_withdrawal_account(self, request):
        serializer = WithdrawalAccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account = self.withdrawal_service.add_withdrawal_account(
            owner=request.user,
            bank_code=serializer.validated_data["bank_code"],
            account_number=serializer.validated_data["account_number"],
            gateway_name=serializer.validated_data["gateway_name"],
            bank_name=serializer.validated_data.get("bank_name"),
        )
        return APIResponse(
            status="success",
            status_code=201,
            message="Account added.",
            data=WithdrawalAccountSerializer(account).data,
        )

    @extend_schema(
        summary="List Withdrawal Accounts",
        responses={200: WithdrawalAccountSerializer(many=True)},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/accounts/list")
    def list_withdrawal_accounts(self, request):
        accounts = WithdrawalAccount.objects.filter(
            user=request.user, is_active=True
        ).order_by("-created_at")
        serializer = WithdrawalAccountSerializer(accounts, many=True)
        return APIResponse(
            status="success",
            status_code=200,
            message="Accounts fetched.",
            data=serializer.data,
        )

    @extend_schema(
        summary="Remove Withdrawal Account",
        responses={200: dict},
        tags=["User › Wallet"],
    )
    @action(detail=True, methods=["DELETE"], url_path="withdrawals/accounts")
    def remove_withdrawal_account(self, request, pk=None):
        self.withdrawal_service.remove_withdrawal_account(request.user, pk)
        return APIResponse(
            status="success",
            status_code=200,
            message="Withdrawal account removed.",
            data={"id": pk},
        )

    @extend_schema(
        summary="Request Withdrawal",
        request=WithdrawalRequestCreateSerializer,
        responses={201: WithdrawalRequestSerializer},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="withdrawals/request")
    def request_withdrawal(self, request):
        serializer = WithdrawalRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        req = self.withdrawal_service.request_withdrawal(
            owner=request.user,
            account_id=serializer.validated_data["account_id"],
            amount=serializer.validated_data["amount"],
        )
        return APIResponse(
            status="success",
            status_code=201,
            message="Withdrawal requested.",
            data=WithdrawalRequestSerializer(req).data,
        )

    @extend_schema(
        summary="List My Withdrawal Requests",
        responses={200: WithdrawalRequestSerializer(many=True)},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/requests")
    def list_withdrawal_requests(self, request):
        reqs = WithdrawalRequest.objects.filter(wallet__user=request.user).order_by(
            "-created_at"
        )
        paginator = WalletPagination()
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
        summary="Get Wallet Financial Summary",
        description="Retrieves the total amount of Skillcoins earned, spent, "
        "and withdrawn by the authenticated user.",
        responses={200: WalletFinancialSummarySerializer},
        tags=["User › Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="summary")
    def get_financial_summary(self, request):
        stats = self.wallet_service.get_user_financial_summary(user=request.user)

        serializer = WalletFinancialSummarySerializer(stats)

        return APIResponse(
            status="success",
            status_code=200,
            message="Financial summary fetched successfully.",
            data=serializer.data,
        )

    @extend_schema(
        summary="Report a transaction",
        description=(
            "Open a support case for a wallet transaction. "
            "Accepts the transaction UUID or reference_id."
        ),
        request=TransactionReportRequestSerializer,
        responses={201: TransactionReportResponseSerializer},
        tags=["User › Wallet"],
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="transactions/(?P<transaction_ref>[^/.]+)/report",
    )
    def report_transaction(self, request, transaction_ref=None):
        serializer = TransactionReportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(
                status="error",
                status_code=400,
                message=serializer.errors,
            )
        try:
            result = self.wallet_service.report_transaction(
                user=request.user,
                ref=transaction_ref,
                reason=serializer.validated_data["reason"],
                details=serializer.validated_data.get("details", ""),
            )
        except ValidationError as e:
            return APIResponse(
                status="error",
                status_code=404,
                message=str(e.detail) if hasattr(e, "detail") else str(e),
            )
        return APIResponse(
            status="success",
            status_code=201,
            message="Transaction report submitted.",
            data=TransactionReportResponseSerializer(result).data,
        )
