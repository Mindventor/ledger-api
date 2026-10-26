"""Immutability, atomicity and database-level safety nets."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database import engine
from app.services import ledger
from tests.conftest import balance_of


def _first_tx(client, acc):
    return client.get(f"/accounts/{acc}/transactions").json()["data"][0]


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_api_has_no_route_to_edit_or_delete_transactions(client, make_account, method):
    acc = make_account(credit=50)
    t = _first_tx(client, acc)
    for path in (f"/transactions/{t['id']}", f"/accounts/{acc}/transactions"):
        r = getattr(client, method)(path)
        assert r.status_code in (404, 405)
    assert _first_tx(client, acc) == t


def test_database_blocks_updating_a_transaction(client, make_account):
    acc = make_account(credit=50)
    t = _first_tx(client, acc)
    for stmt in (
        "UPDATE transactions SET amount = 999 WHERE id = :id",
        "UPDATE transactions SET type = 'debit' WHERE id = :id",
        "UPDATE transactions SET description = 'edited' WHERE id = :id",
        "UPDATE transactions SET reference_id = 'other' WHERE id = :id",
        "UPDATE transactions SET created_at = now() - interval '1 day' WHERE id = :id",
        "DELETE FROM transactions WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as conn:
                conn.execute(text(stmt), {"id": t["id"]})
    assert _first_tx(client, acc) == t


def test_database_rejects_negative_balance(make_account):
    acc = make_account(credit=10)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE accounts SET balance = -1 WHERE id = :id"), {"id": acc})


def test_database_enforces_unique_reference_per_account(make_account):
    acc = make_account()
    insert = text("INSERT INTO transactions (account_id, type, amount, reference_id) VALUES (:a, 'credit', 1, 'dup')")
    with engine.begin() as conn:
        conn.execute(insert, {"a": acc})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert, {"a": acc})


def test_failure_after_insert_rolls_back_everything(client, make_account, tx, monkeypatch):
    """If something breaks after the transaction row is written but before
    commit, neither the row nor the balance change may survive."""
    acc = make_account(credit=100)
    real_commit = ledger.Session.commit

    def broken_commit(self):
        raise RuntimeError("simulated crash before commit")

    monkeypatch.setattr(ledger.Session, "commit", broken_commit)
    with pytest.raises(RuntimeError):
        ledger.add_transaction(
            ledger.Session(bind=engine),
            ledger.TransactionCreate(account_id=acc, type="debit", amount="40", reference_id="boom"),
        )
    monkeypatch.setattr(ledger.Session, "commit", real_commit)

    assert balance_of(client, acc) == "100.00"
    refs = [r["reference_id"] for r in client.get(f"/accounts/{acc}/transactions").json()["data"]]
    assert "boom" not in refs
    # The same reference can be used again because nothing was stored.
    assert tx(acc, "debit", 40, "boom").status_code == 201
    assert balance_of(client, acc) == "60.00"
