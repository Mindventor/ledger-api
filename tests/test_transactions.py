import uuid

import pytest

from tests.conftest import balance_of


def test_credit_increases_balance(client, make_account, tx):
    acc = make_account(credit=100)
    r = tx(acc, "credit", 50, "c1", "top-up")
    assert r.status_code == 201
    body = r.json()
    assert body["balance"] == "150.00"
    t = body["transaction"]
    assert t["type"] == "credit" and t["amount"] == "50.00" and t["description"] == "top-up"
    assert t["reference_id"] == "c1" and t["account_id"] == acc
    uuid.UUID(t["id"])
    assert t["created_at"]


def test_debit_decreases_balance(client, make_account, tx):
    acc = make_account(credit=100)
    r = tx(acc, "debit", 30, "d1")
    assert r.status_code == 201
    assert r.json()["balance"] == "70.00"


def test_debit_with_insufficient_balance_is_rejected(client, make_account, tx):
    acc = make_account(credit=100)
    r = tx(acc, "debit", 150, "d1")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "INSUFFICIENT_BALANCE"
    assert err["details"]["balance"] == "100.00" and err["details"]["requested"] == "150.00"
    assert balance_of(client, acc) == "100.00"
    # The rejected debit is not recorded anywhere.
    history = client.get(f"/accounts/{acc}/transactions").json()
    assert history["pagination"]["total_records"] == 1


def test_debit_of_exact_balance_is_allowed(client, make_account, tx):
    acc = make_account(credit=100)
    assert tx(acc, "debit", 100, "d1").status_code == 201
    assert balance_of(client, acc) == "0.00"


def test_debit_on_empty_account_is_rejected(client, make_account, tx):
    acc = make_account()
    assert tx(acc, "debit", "0.01", "d1").status_code == 422


def test_example_sequence_from_brief(client, make_account, tx):
    acc = make_account()
    for i, (kind, amount) in enumerate([("credit", 100), ("credit", 50), ("debit", 30), ("debit", 20)]):
        assert tx(acc, kind, amount, f"r{i}").status_code == 201
    assert balance_of(client, acc) == "100.00"


def test_duplicate_reference_does_not_create_or_change_anything(client, make_account, tx):
    acc = make_account(credit=100)
    first = tx(acc, "debit", 40, "order-1")
    assert first.status_code == 201

    again = tx(acc, "debit", 40, "order-1")
    assert again.status_code == 409
    err = again.json()["error"]
    assert err["code"] == "DUPLICATE_TRANSACTION"
    assert err["details"]["existing_transaction"]["id"] == first.json()["transaction"]["id"]
    assert balance_of(client, acc) == "60.00"
    assert client.get(f"/accounts/{acc}/transactions").json()["pagination"]["total_records"] == 2


def test_duplicate_reference_with_different_payload_is_still_a_duplicate(client, make_account, tx):
    acc = make_account(credit=100)
    tx(acc, "debit", 40, "order-1")
    r = tx(acc, "credit", 999, "order-1")
    assert r.status_code == 409
    assert balance_of(client, acc) == "60.00"


def test_retried_debit_reports_duplicate_not_insufficient_balance(client, make_account, tx):
    acc = make_account(credit=100)
    assert tx(acc, "debit", 100, "pay-1").status_code == 201
    # Balance is now 0; a retry must say "already exists", not "insufficient".
    assert tx(acc, "debit", 100, "pay-1").status_code == 409


def test_same_reference_allowed_on_different_accounts(client, make_account, tx):
    a, b = make_account(credit=10), make_account(credit=10)
    assert tx(a, "credit", 5, "shared-ref").status_code == 201
    assert tx(b, "credit", 5, "shared-ref").status_code == 201
    assert balance_of(client, a) == "15.00" and balance_of(client, b) == "15.00"


def test_unknown_account_is_404(client, tx):
    r = tx(str(uuid.uuid4()), "credit", 10, "x")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


@pytest.mark.parametrize("amount", [0, -5, "0", "-0.01", "abc", None, "1.234", "NaN", "Infinity", 1e30])
def test_invalid_amounts_are_rejected(client, make_account, tx, amount):
    acc = make_account(credit=100)
    r = tx(acc, "credit", amount, "bad")
    assert r.status_code == 400, (amount, r.text)
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert balance_of(client, acc) == "100.00"


@pytest.mark.parametrize("tx_type", ["deposit", "CREDIT", "", None, 1])
def test_invalid_type_is_rejected(client, make_account, tx, tx_type):
    acc = make_account()
    assert tx(acc, tx_type, 10, "bad").status_code == 400


@pytest.mark.parametrize("ref", ["", "   ", None, "x" * 101])
def test_reference_id_is_required(client, make_account, tx, ref):
    acc = make_account()
    assert tx(acc, "credit", 10, ref).status_code == 400


def test_missing_fields_are_listed(client):
    r = client.post("/transactions", json={})
    assert r.status_code == 400
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"account_id", "type", "amount", "reference_id"} <= fields


def test_invalid_account_id_format_is_400(client, tx):
    assert tx("not-a-uuid", "credit", 10, "x").status_code == 400


def test_decimal_amounts_are_exact(client, make_account, tx):
    acc = make_account()
    for i in range(10):
        tx(acc, "credit", "0.10", f"c{i}")
    tx(acc, "debit", "0.30", "d1")
    assert balance_of(client, acc) == "0.70"


def test_balance_always_equals_sum_of_transactions(client, make_account, tx):
    acc = make_account()
    ops = [("credit", "100"), ("debit", "30.50"), ("debit", "500"), ("credit", "12.25"), ("debit", "81.75")]
    for i, (kind, amount) in enumerate(ops):
        tx(acc, kind, amount, f"op{i}")  # the 500 debit is rejected
    rows = client.get(f"/accounts/{acc}/transactions?limit=100").json()["data"]
    total = sum(float(r["amount"]) * (1 if r["type"] == "credit" else -1) for r in rows)
    assert f"{total:.2f}" == balance_of(client, acc) == "0.00"
