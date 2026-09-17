# ruff: noqa: I
# isort: skip_file
from tests.concurrency.base import get_withdrawal_service, init_worker

from decimal import Decimal
from multiprocessing import Pool

from skiflux.models import User
from skiflux.models.wallet import (
    SystemFinancialConfig,
    WithdrawalAccount,
    WithdrawalHold,
    WithdrawalRequest,
)
from skiflux.services.wallet_service import WalletService


def _attempt_withdrawal(args):
    user_id, account_id, amount = args

    # Fresh connection per process
    from django.db import connection

    connection.close()

    user = User.objects.get(id=user_id)
    account = WithdrawalAccount.objects.get(id=account_id)

    svc = get_withdrawal_service()
    try:
        req = svc.request_withdrawal(user, str(account.id), amount)
        return ("success", str(req.id))
    except Exception as e:
        return ("error", str(e))


def test_concurrent_withdrawal_requests_cannot_double_spend():
    # Setup (runs in main process)
    user = User.objects.create(
        email="race@test.com", first_name="Race", last_name="Test"
    )
    ws = WalletService()
    ws.credit_wallet(user, Decimal("1000.00"), "TOPUP", "Initial funding")

    account = WithdrawalAccount.objects.create(
        user=user,
        bank_code="044",
        account_number="1234567890",
        account_name="Race Test",
        status=WithdrawalAccount.Status.VERIFIED,
    )

    config = SystemFinancialConfig.get_config()
    config.min_withdrawal_amount = Decimal("100.00")
    config.withdrawal_fee_percentage = Decimal("0.00")
    config.require_withdrawal_approval = True
    config.save()

    with Pool(2, initializer=init_worker) as pool:
        results = pool.map(
            _attempt_withdrawal,
            [
                (user.id, account.id, Decimal("900.00")),
                (user.id, account.id, Decimal("900.00")),
            ],
        )

    successes = [r for r in results if r[0] == "success"]
    errors = [r for r in results if r[0] == "error"]

    print("Results:", results)

    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
    assert len(errors) == 1

    holds = WithdrawalHold.objects.filter(
        wallet__user=user, status=WithdrawalHold.Status.ACTIVE
    )
    assert holds.count() == 1

    requests = WithdrawalRequest.objects.filter(wallet__user=user)
    assert requests.count() == 1


if __name__ == "__main__":
    print("Running: test_concurrent_withdrawal_requests_cannot_double_spend")
    test_concurrent_withdrawal_requests_cannot_double_spend()
    print("Test completed.")
