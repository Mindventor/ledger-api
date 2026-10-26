import uuid

from tests.conftest import balance_of


def test_create_account_starts_at_zero(client):
    r = client.post("/accounts", json={"name": "Asha"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Asha"
    assert body["balance"] == "0.00"
    uuid.UUID(body["id"])
    assert body["created_at"]


def test_account_ids_are_unique(client):
    ids = {client.post("/accounts", json={"name": f"u{i}"}).json()["id"] for i in range(5)}
    assert len(ids) == 5


def test_client_cannot_set_initial_balance(client):
    r = client.post("/accounts", json={"name": "Sneaky", "balance": 500})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert r.json()["error"]["details"][0]["field"] == "balance"


def test_client_cannot_set_id_or_created_at(client):
    r = client.post("/accounts", json={"name": "x", "id": str(uuid.uuid4()), "created_at": "2020-01-01T00:00:00Z"})
    assert r.status_code == 400


def test_name_is_required(client):
    for payload in ({}, {"name": ""}, {"name": "   "}, {"name": None}):
        r = client.post("/accounts", json=payload)
        assert r.status_code == 400, payload
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_name_is_trimmed(client):
    assert client.post("/accounts", json={"name": "  Ravi  "}).json()["name"] == "Ravi"


def test_malformed_json_is_rejected(client):
    r = client.post("/accounts", content="{name: oops", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_balance_endpoint(client, make_account):
    acc = make_account(credit=250)
    r = client.get(f"/accounts/{acc}/balance")
    assert r.status_code == 200
    assert r.json() == {"account_id": acc, "balance": "250.00"}


def test_balance_unknown_account_is_404(client):
    r = client.get(f"/accounts/{uuid.uuid4()}/balance")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_balance_invalid_account_id_is_400(client):
    r = client.get("/accounts/12345/balance")
    assert r.status_code == 400
    assert r.json()["error"]["details"][0]["field"] == "account_id"


def test_get_account(client, make_account):
    acc = make_account(name="Meera", credit=10)
    body = client.get(f"/accounts/{acc}").json()
    assert body["name"] == "Meera" and body["balance"] == "10.00"
    assert balance_of(client, acc) == "10.00"
