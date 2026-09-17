from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from skiflux.gateways.registry import PaymentGatewayFactory
from skiflux.models.wallet import WithdrawalAccount, WithdrawalRequest
from skiflux.serializers.wallet import (
    AddCardSerializer,
    ChargeSavedCardSerializer,
    ConnectOnboardSerializer,
    PaymentTransactionSerializer,
    SavedCardSerializer,
    TopupInitiateSerializer,
    UserWalletSerializer,
    VerifyPaymentSerializer,
    WithdrawalAccountCreateSerializer,
    WithdrawalAccountSerializer,
    WithdrawalRequestCreateSerializer,
    WithdrawalRequestSerializer,
)
from skiflux.services.card_service import CardService
from skiflux.services.payment_service import PaymentService
from skiflux.services.wallet_service import WalletService
from skiflux.services.withdrawal_service import WithdrawalService
from skiflux.utils import AdminJWTAuthentication, APIResponse


class AdminSelfWalletPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = "page_size"
    max_page_size = 50


class AdminSelfWalletViewSet(viewsets.ViewSet):
    """Self-service wallet operations for AdminUsers (including creators):
    top up their own wallet and withdraw their own earnings. Mirrors the
    user-facing wallet surface; every action operates on the caller's own
    wallet, so no special permission beyond authentication is required."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = UserWalletSerializer

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wallet_service = WalletService()
        self.payment_service = PaymentService()
        self.withdrawal_service = WithdrawalService()
        self.card_service = CardService()

    # --- Wallet -------------------------------------------------------------

    @extend_schema(
        summary="Fetch My Wallet Balance (Admin/Creator)",
        responses={200: UserWalletSerializer},
        tags=["Admin › My Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="my-wallet")
    def retrieve_my_wallet(self, request):
        wallet = self.wallet_service.get_or_create_wallet(request.user)
        return APIResponse(
            status="success",
            status_code=200,
            message="Wallet balance fetched.",
            data=UserWalletSerializer(wallet).data,
        )

    # --- Top-up --------------------------------------------------------------

    @extend_schema(
        summary="List Top-up Methods (Admin/Creator)",
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="Initiate Wallet Top-up (Admin/Creator)",
        request=TopupInitiateSerializer,
        responses={200: dict},
        tags=["Admin › My Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="topup/initiate")
    def initiate_topup(self, request):
        serializer = TopupInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

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
        summary="Verify Top-up (Admin/Creator)",
        request=VerifyPaymentSerializer,
        responses={200: dict},
        tags=["Admin › My Wallet"],
    )
    @action(detail=False, methods=["POST"], url_path="topup/verify")
    def verify_topup(self, request):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tx = self.payment_service.verify_payment(
            tx_ref=serializer.validated_data["tx_ref"],
            requesting_user=request.user,
            gateway_reference=serializer.validated_data.get("gateway_reference"),
        )
        return APIResponse(
            status="success",
            status_code=200,
            message="Top-up verified.",
            data={"status": tx.status, "amount_skillcoins": tx.amount_skillcoins},
        )

    @extend_schema(
        summary="Top-up With a Saved Card (Admin/Creator)",
        request=ChargeSavedCardSerializer,
        responses={200: PaymentTransactionSerializer},
        tags=["Admin › My Wallet"],
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

    # --- Saved cards ----------------------------------------------------------

    @extend_schema(
        summary="Add a Card (Admin/Creator)",
        request=AddCardSerializer,
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="List My Saved Cards (Admin/Creator)",
        responses={200: SavedCardSerializer(many=True)},
        tags=["Admin › My Wallet"],
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
        summary="Remove a Saved Card (Admin/Creator)",
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="Set Default Saved Card (Admin/Creator)",
        responses={200: SavedCardSerializer},
        tags=["Admin › My Wallet"],
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

    # --- Withdrawals -----------------------------------------------------------

    @extend_schema(
        summary="List Withdrawal Methods (Admin/Creator)",
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="Get Supported Banks (Admin/Creator)",
        parameters=[
            OpenApiParameter(
                name="gateway",
                description="Gateway to get banks for. Defaults to paystack.",
                required=False,
                type=str,
            ),
        ],
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="Add Withdrawal Account (Admin/Creator)",
        request=WithdrawalAccountCreateSerializer,
        responses={201: WithdrawalAccountSerializer},
        tags=["Admin › My Wallet"],
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
        summary="List Withdrawal Accounts (Admin/Creator)",
        responses={200: WithdrawalAccountSerializer(many=True)},
        tags=["Admin › My Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/accounts/list")
    def list_withdrawal_accounts(self, request):
        accounts = WithdrawalAccount.objects.filter(
            admin_user=request.user, is_active=True
        ).order_by("-created_at")
        return APIResponse(
            status="success",
            status_code=200,
            message="Accounts fetched.",
            data=WithdrawalAccountSerializer(accounts, many=True).data,
        )

    @extend_schema(
        summary="Remove Withdrawal Account (Admin/Creator)",
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="Start Stripe Connect Withdrawal Setup (Admin/Creator)",
        request=ConnectOnboardSerializer,
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="Check Stripe Connect Withdrawal Status (Admin/Creator)",
        responses={200: dict},
        tags=["Admin › My Wallet"],
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
        summary="Request Withdrawal (Admin/Creator)",
        request=WithdrawalRequestCreateSerializer,
        responses={201: WithdrawalRequestSerializer},
        tags=["Admin › My Wallet"],
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
        summary="List My Withdrawal Requests (Admin/Creator)",
        responses={200: WithdrawalRequestSerializer(many=True)},
        tags=["Admin › My Wallet"],
    )
    @action(detail=False, methods=["GET"], url_path="withdrawals/requests")
    def list_withdrawal_requests(self, request):
        reqs = WithdrawalRequest.objects.filter(
            wallet__admin_user=request.user
        ).order_by("-created_at")
        paginator = AdminSelfWalletPagination()
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
