# ruff: noqa: I
# isort: skip_file
from tests.concurrency.base import get_withdrawal_service, init_worker

import uuid
from decimal import Decimal
from multiprocessing import Pool

from skiflux.models import User
from skiflux.models.wallet import (
    SystemFinancialConfig,
    WithdrawalAccount,
    WithdrawalHold,
    WithdrawalRequest,
    SkillcoinTransaction,
)
from skiflux.services.wallet_service import WalletService


def _complete_withdrawal(request_id):
    from django.db import connection

    connection.close()

    svc = get_withdrawal_service()
    try:
        svc.mark_withdrawal_completed(request_id)
        return "success"
    except Exception as e:
        return f"error: {e}"


def test_concurrent_withdrawal_completion_is_idempotent():
    unique = uuid.uuid4().hex[:8]
    user = User.objects.create(
        email=f"completion-{unique}@test.com",
        first_name="Complete",
        last_name="Test",
    )
    ws = WalletService()
    ws.credit_wallet(user, Decimal("1000.00"), "TOPUP", "Funding")

    account = WithdrawalAccount.objects.create(
        user=user,
        bank_code="044",
        account_number="0000000001",
        account_name="Complete Test",
        status=WithdrawalAccount.Status.VERIFIED,
    )

    config = SystemFinancialConfig.get_config()
    config.min_withdrawal_amount = Decimal("100.00")
    config.withdrawal_fee_percentage = Decimal("0.00")
    config.require_withdrawal_approval = True
    config.save()

    svc = get_withdrawal_service()
    req = svc.request_withdrawal(user, str(account.id), Decimal("500.00"))

    with Pool(5, initializer=init_worker) as pool:
        results = pool.map(_complete_withdrawal, [str(req.id)] * 5)

    print("Completion results:", results)

    wallet = ws.get_or_create_wallet(user)
    wallet.refresh_from_db()

    assert wallet.balance == Decimal("500.00")

    hold = WithdrawalHold.objects.get(withdrawal_request=req)
    assert hold.status == WithdrawalHold.Status.CONVERTED

    req.refresh_from_db()
    assert req.status == WithdrawalRequest.Status.COMPLETED

    active_holds = WithdrawalHold.objects.filter(
        withdrawal_request=req,
        status=WithdrawalHold.Status.ACTIVE,
    )
    count = SkillcoinTransaction.objects.filter(
        reference_id=req.id,
        transaction_type=SkillcoinTransaction.Type.WITHDRAWAL,
        status=SkillcoinTransaction.Status.POSTED,
    ).count()

    fee_count = SkillcoinTransaction.objects.filter(
        reference_id=req.id,
        transaction_type=SkillcoinTransaction.Type.WITHDRAWAL_FEE,
        status=SkillcoinTransaction.Status.POSTED,
    ).count()

    print(f"Final wallet balance: {wallet.balance}")
    print(f"Hold status: {hold.status}")
    print(f"Number of active holds for this wallet: {active_holds.count()}")
    print(f"Number of POSTED WITHDRAWAL transactions for this request: {count}")
    print(f"Number of POSTED WITHDRAWAL_FEE transactions: {fee_count}")
    assert count == 1, f"Expected exactly 1 WITHDRAWAL transaction, got {count}"
    assert fee_count == 1 or hold.fee == 0, (
        f"Expected 1 WITHDRAWAL_FEE transaction, got {fee_count}"
    )


if __name__ == "__main__":
    print("Running: test_concurrent_withdrawal_completion_is_idempotent")
    test_concurrent_withdrawal_completion_is_idempotent()
    print("Test completed.")
