import uuid

import pytest

from app.services import ledger
from tests.conftest import balance_of


def transfer(client, src, dst, amount, ref="t1", description=None):
    body = {"from_account_id": src, "to_account_id": dst, "amount": amount, "reference_id": ref}
    if description:
        body["description"] = description
    return client.post("/transfers", json=body)


def test_transfer_moves_money(client, make_account):
    a, b = make_account(credit=100), make_account(credit=50)
    r = transfer(client, a, b, 30, description="rent share")
    assert r.status_code == 201
    body = r.json()
    assert body["from_account_balance"] == "70.00" and body["to_account_balance"] == "80.00"
    assert body["transfer"]["amount"] == "30.00"
    assert balance_of(client, a) == "70.00" and balance_of(client, b) == "80.00"


def test_transfer_creates_linked_ledger_entries(client, make_account):
    a, b = make_account(credit=100), make_account()
    t = transfer(client, a, b, 30).json()["transfer"]
    out = client.get(f"/accounts/{a}/transactions?type=debit").json()["data"]
    inc = client.get(f"/accounts/{b}/transactions?type=credit").json()["data"]
    assert out[0]["transfer_id"] == inc[0]["transfer_id"] == t["id"]
    assert out[0]["amount"] == inc[0]["amount"] == "30.00"


def test_insufficient_balance_changes_nothing(client, make_account):
    a, b = make_account(credit=100), make_account(credit=50)
    r = transfer(client, a, b, 150)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert balance_of(client, a) == "100.00" and balance_of(client, b) == "50.00"
    assert client.get(f"/accounts/{b}/transactions").json()["pagination"]["total_records"] == 1


def test_unknown_destination_changes_nothing(client, make_account):
    a = make_account(credit=100)
    r = transfer(client, a, str(uuid.uuid4()), 10)
    assert r.status_code == 404
    assert balance_of(client, a) == "100.00"


def test_unknown_source(client, make_account):
    b = make_account()
    assert transfer(client, str(uuid.uuid4()), b, 10).status_code == 404


def test_same_account_is_rejected(client, make_account):
    a = make_account(credit=100)
    r = transfer(client, a, a, 10)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_TRANSFER"


def test_duplicate_transfer_reference(client, make_account):
    a, b = make_account(credit=100), make_account()
    first = transfer(client, a, b, 10, ref="tr-1")
    again = transfer(client, a, b, 10, ref="tr-1")
    assert again.status_code == 409
    assert again.json()["error"]["details"]["existing_transfer"]["id"] == first.json()["transfer"]["id"]
    assert balance_of(client, a) == "90.00" and balance_of(client, b) == "10.00"


@pytest.mark.parametrize("amount", [0, -1, "1.001", "x"])
def test_invalid_amount(client, make_account, amount):
    a, b = make_account(credit=100), make_account()
    assert transfer(client, a, b, amount).status_code == 400


def test_failure_on_credit_side_rolls_back_debit(client, make_account, monkeypatch):
    """Debit applied, then the credit fails: the debit must be undone too."""
    a, b = make_account(credit=100), make_account()
    real_apply = ledger._apply

    def failing_apply(account, tx_type, amount):
        if tx_type == "credit":
            raise RuntimeError("simulated failure while crediting")
        real_apply(account, tx_type, amount)

    monkeypatch.setattr(ledger, "_apply", failing_apply)
    with pytest.raises(RuntimeError):
        client.post("/transfers", json={"from_account_id": a, "to_account_id": b, "amount": 30, "reference_id": "x"})
    monkeypatch.setattr(ledger, "_apply", real_apply)

    assert balance_of(client, a) == "100.00" and balance_of(client, b) == "0.00"
    # No transfer row was kept, so the same reference works afterwards.
    assert transfer(client, a, b, 30, ref="x").status_code == 201
