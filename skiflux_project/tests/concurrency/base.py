import os

import django
from django.conf import settings

if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "skiflux_project.settings")
    django.setup()

from contextlib import contextmanager

from django.db import connection

from skiflux.services.wallet_service import WalletService
from skiflux.services.withdrawal_service import WithdrawalService


def init_worker():
    """Initialize Django in each worker process."""
    django.setup()


@contextmanager
def get_fresh_connection():
    """Ensure each operation uses a fresh connection (important for multiprocessing)."""
    connection.close()
    yield
    connection.close()


def get_withdrawal_service():
    return WithdrawalService()


def get_wallet_service():
    return WalletService()
