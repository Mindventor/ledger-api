"""Requests hitting the same account at the same moment.

Each worker uses its own database session, the same way separate HTTP
requests would, so these tests exercise the row locks for real.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from app.database import SessionLocal
from app.errors import ApiError, DuplicateTransaction, InsufficientBalance
from app.schemas import TransactionCreate, TransferCreate
from app.services import ledger
from tests.conftest import balance_of


def _run(fn, payloads, workers=20):
    def call(p):
        session = SessionLocal()
        try:
            fn(session, p)
            return "ok"
        except ApiError as exc:
            return exc.code
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(call, payloads))


def test_parallel_debits_never_overdraw(client, make_account):
    acc = make_account(credit=100)
    payloads = [TransactionCreate(account_id=acc, type="debit", amount=Decimal("10"), reference_id=f"d{i}") for i in range(25)]
    results = _run(ledger.add_transaction, payloads)
    assert results.count("ok") == 10
    assert results.count(InsufficientBalance.code) == 15
    assert balance_of(client, acc) == "0.00"


def test_parallel_requests_with_same_reference_apply_once(client, make_account):
    acc = make_account()
    payloads = [TransactionCreate(account_id=acc, type="credit", amount=Decimal("5"), reference_id="same") for _ in range(15)]
    results = _run(ledger.add_transaction, payloads)
    assert results.count("ok") == 1
    assert results.count(DuplicateTransaction.code) == 14
    assert balance_of(client, acc) == "5.00"


def test_opposite_transfers_do_not_deadlock_and_conserve_money(client, make_account):
    a, b = make_account(credit=500), make_account(credit=500)
    payloads = []
    for i in range(30):
        src, dst = (a, b) if i % 2 == 0 else (b, a)
        payloads.append(TransferCreate(from_account_id=src, to_account_id=dst, amount=Decimal("7"), reference_id=f"t{i}"))
    results = _run(ledger.transfer, payloads, workers=10)
    assert results.count("ok") == 30
    total = Decimal(balance_of(client, a)) + Decimal(balance_of(client, b))
    assert total == Decimal("1000.00")
    assert balance_of(client, a) == "500.00"  # 15 out, 15 in, same amount
