from django.urls import path

from skiflux.views.admin_self_wallet import AdminSelfWalletViewSet
from skiflux.views.admin_wallet import AdminLedgerViewSet
from skiflux.views.wallet import UserWalletViewSet

urlpatterns = [
    path(
        "wallet/my-wallet",
        UserWalletViewSet.as_view({"get": "retrieve_my_wallet"}),
        name="user-wallet-detail",
    ),
    path(
        "wallet/summary",
        UserWalletViewSet.as_view({"get": "get_financial_summary"}),
        name="user-wallet-summary",
    ),
    path(
        "wallet/my-transactions",
        UserWalletViewSet.as_view({"get": "list_my_transactions"}),
        name="user-transactions-list",
    ),
    path(
        "wallet/transactions/<str:transaction_ref>/report",
        UserWalletViewSet.as_view({"post": "report_transaction"}),
        name="user-transaction-report",
    ),
    path(
        "wallet/topup/initiate",
        UserWalletViewSet.as_view({"post": "initiate_topup"}),
        name="user-wallet-topup-initiate",
    ),
    path(
        "wallet/topup/verify",
        UserWalletViewSet.as_view({"post": "verify_topup"}),
        name="user-wallet-topup-verify",
    ),
    path(
        "wallet/topup/methods",
        UserWalletViewSet.as_view({"get": "get_topup_methods"}),
        name="user-wallet-topup-methods",
    ),
    path(
        "wallet/topup/charge-card",
        UserWalletViewSet.as_view({"post": "charge_saved_card"}),
        name="user-wallet-topup-charge-card",
    ),
    path(
        "wallet/cards/add",
        UserWalletViewSet.as_view({"post": "add_card"}),
        name="user-wallet-cards-add",
    ),
    path(
        "wallet/cards",
        UserWalletViewSet.as_view({"get": "list_cards"}),
        name="user-wallet-cards-list",
    ),
    path(
        "wallet/cards/<uuid:pk>",
        UserWalletViewSet.as_view({"delete": "remove_card"}),
        name="user-wallet-cards-remove",
    ),
    path(
        "wallet/cards/<uuid:pk>/set-default",
        UserWalletViewSet.as_view({"post": "set_default_card"}),
        name="user-wallet-cards-set-default",
    ),
    path(
        "wallet/withdrawals/banks",
        UserWalletViewSet.as_view({"get": "get_withdrawal_banks"}),
        name="user-wallet-withdrawals-banks",
    ),
    path(
        "wallet/withdrawals/methods",
        UserWalletViewSet.as_view({"get": "get_withdrawal_methods"}),
        name="user-wallet-withdrawals-methods",
    ),
    path(
        "wallet/withdrawals/connect/onboard",
        UserWalletViewSet.as_view({"post": "connect_onboard"}),
        name="user-wallet-withdrawals-connect-onboard",
    ),
    path(
        "wallet/withdrawals/connect/status",
        UserWalletViewSet.as_view({"get": "connect_status"}),
        name="user-wallet-withdrawals-connect-status",
    ),
    path(
        "wallet/withdrawals/accounts",
        UserWalletViewSet.as_view({"post": "add_withdrawal_account"}),
        name="user-wallet-withdrawals-accounts-add",
    ),
    path(
        "wallet/withdrawals/accounts/list",
        UserWalletViewSet.as_view({"get": "list_withdrawal_accounts"}),
        name="user-wallet-withdrawals-accounts-list",
    ),
    path(
        "wallet/withdrawals/accounts/<uuid:pk>",
        UserWalletViewSet.as_view({"delete": "remove_withdrawal_account"}),
        name="user-wallet-withdrawals-accounts-remove",
    ),
    path(
        "wallet/withdrawals/request",
        UserWalletViewSet.as_view({"post": "request_withdrawal"}),
        name="user-wallet-withdrawals-request",
    ),
    path(
        "wallet/withdrawals/requests",
        UserWalletViewSet.as_view({"get": "list_withdrawal_requests"}),
        name="user-wallet-withdrawals-requests-list",
    ),
    # --- Admin/Creator self-service wallet (own wallet, own earnings) ---
    path(
        "admin/wallet/my/my-wallet",
        AdminSelfWalletViewSet.as_view({"get": "retrieve_my_wallet"}),
        name="admin-self-wallet-detail",
    ),
    path(
        "admin/wallet/my/topup/methods",
        AdminSelfWalletViewSet.as_view({"get": "get_topup_methods"}),
        name="admin-self-wallet-topup-methods",
    ),
    path(
        "admin/wallet/my/topup/initiate",
        AdminSelfWalletViewSet.as_view({"post": "initiate_topup"}),
        name="admin-self-wallet-topup-initiate",
    ),
    path(
        "admin/wallet/my/topup/verify",
        AdminSelfWalletViewSet.as_view({"post": "verify_topup"}),
        name="admin-self-wallet-topup-verify",
    ),
    path(
        "admin/wallet/my/topup/charge-card",
        AdminSelfWalletViewSet.as_view({"post": "charge_saved_card"}),
        name="admin-self-wallet-topup-charge-card",
    ),
    path(
        "admin/wallet/my/cards/add",
        AdminSelfWalletViewSet.as_view({"post": "add_card"}),
        name="admin-self-wallet-cards-add",
    ),
    path(
        "admin/wallet/my/cards",
        AdminSelfWalletViewSet.as_view({"get": "list_cards"}),
        name="admin-self-wallet-cards-list",
    ),
    path(
        "admin/wallet/my/cards/<uuid:pk>",
        AdminSelfWalletViewSet.as_view({"delete": "remove_card"}),
        name="admin-self-wallet-cards-remove",
    ),
    path(
        "admin/wallet/my/cards/<uuid:pk>/set-default",
        AdminSelfWalletViewSet.as_view({"post": "set_default_card"}),
        name="admin-self-wallet-cards-set-default",
    ),
    path(
        "admin/wallet/my/withdrawals/methods",
        AdminSelfWalletViewSet.as_view({"get": "get_withdrawal_methods"}),
        name="admin-self-wallet-withdrawals-methods",
    ),
    path(
        "admin/wallet/my/withdrawals/banks",
        AdminSelfWalletViewSet.as_view({"get": "get_withdrawal_banks"}),
        name="admin-self-wallet-withdrawals-banks",
    ),
    path(
        "admin/wallet/my/withdrawals/accounts",
        AdminSelfWalletViewSet.as_view({"post": "add_withdrawal_account"}),
        name="admin-self-wallet-withdrawals-accounts-add",
    ),
    path(
        "admin/wallet/my/withdrawals/accounts/list",
        AdminSelfWalletViewSet.as_view({"get": "list_withdrawal_accounts"}),
        name="admin-self-wallet-withdrawals-accounts-list",
    ),
    path(
        "admin/wallet/my/withdrawals/accounts/<uuid:pk>",
        AdminSelfWalletViewSet.as_view({"delete": "remove_withdrawal_account"}),
        name="admin-self-wallet-withdrawals-accounts-remove",
    ),
    path(
        "admin/wallet/my/withdrawals/connect/onboard",
        AdminSelfWalletViewSet.as_view({"post": "connect_onboard"}),
        name="admin-self-wallet-withdrawals-connect-onboard",
    ),
    path(
        "admin/wallet/my/withdrawals/connect/status",
        AdminSelfWalletViewSet.as_view({"get": "connect_status"}),
        name="admin-self-wallet-withdrawals-connect-status",
    ),
    path(
        "admin/wallet/my/withdrawals/request",
        AdminSelfWalletViewSet.as_view({"post": "request_withdrawal"}),
        name="admin-self-wallet-withdrawals-request",
    ),
    path(
        "admin/wallet/my/withdrawals/requests",
        AdminSelfWalletViewSet.as_view({"get": "list_withdrawal_requests"}),
        name="admin-self-wallet-withdrawals-requests-list",
    ),
    path(
        "admin/finance/ledger-audit",
        AdminLedgerViewSet.as_view({"get": "audit_global_ledger"}),
        name="admin-ledger-audit",
    ),
    path(
        "admin/finance/manual-adjustment",
        AdminLedgerViewSet.as_view({"post": "manual_adjustment"}),
        name="admin-wallet-adjust",
    ),
    path(
        "admin/finance/toggle-lock",
        AdminLedgerViewSet.as_view({"post": "toggle_lock"}),
        name="admin-wallet-lock",
    ),
    path(
        "admin/finance/issue-refund",
        AdminLedgerViewSet.as_view({"post": "issue_refund"}),
        name="admin-purchase-refund",
    ),
    path(
        "admin/finance/verify-integrity",
        AdminLedgerViewSet.as_view({"post": "verify_wallet_integrity"}),
        name="admin-wallet-verify",
    ),
    path(
        "admin/finance/financial-config",
        AdminLedgerViewSet.as_view(
            {"get": "manage_financial_config", "patch": "manage_financial_config"}
        ),
        name="admin-financial-config",
    ),
    path(
        "admin/finance/currencies",
        AdminLedgerViewSet.as_view(
            {"get": "manage_currencies", "post": "manage_currencies"}
        ),
        name="admin-currencies",
    ),
    path(
        "admin/finance/withdrawals/requests",
        AdminLedgerViewSet.as_view({"get": "list_withdrawal_requests"}),
        name="admin-withdrawals-requests-list",
    ),
    path(
        "admin/finance/withdrawals/process",
        AdminLedgerViewSet.as_view({"post": "process_withdrawal"}),
        name="admin-withdrawals-process",
    ),
    path(
        "admin/finance/payment-transactions",
        AdminLedgerViewSet.as_view({"get": "list_payment_transactions"}),
        name="admin-payment-transactions-list",
    ),
    path(
        "admin/finance/gateway-fees",
        AdminLedgerViewSet.as_view({"get": "get_gateway_fees"}),
        name="admin-gateway-fees-list",
    ),
    path(
        "admin/finance/gateway-fees/update",
        AdminLedgerViewSet.as_view({"post": "update_gateway_fees"}),
        name="admin-gateway-fees-update",
    ),
    path(
        "admin/finance/gateway-fees/<int:config_id>",
        AdminLedgerViewSet.as_view({"delete": "delete_gateway_fee"}),
        name="admin-gateway-fees-delete",
    ),
]
