import os

# Point the app at the test database before anything imports app.database.
os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://ledger:ledger@localhost:5432/ledger_test"),
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import apply_migrations, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _schema():
    apply_migrations()
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    # TRUNCATE does not fire row-level triggers, so the immutability
    # trigger does not get in the way of resetting test data.
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE transactions, transfers, accounts RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_account(client):
    def _make(name="Test User", credit=None):
        acc = client.post("/accounts", json={"name": name}).json()
        if credit is not None:
            r = client.post("/transactions", json={
                "account_id": acc["id"], "type": "credit", "amount": str(credit),
                "reference_id": f"seed-{acc['id']}",
            })
            assert r.status_code == 201, r.text
        return acc["id"]
    return _make


@pytest.fixture
def tx(client):
    def _tx(account_id, tx_type, amount, ref, description=None):
        body = {"account_id": account_id, "type": tx_type, "amount": amount, "reference_id": ref}
        if description is not None:
            body["description"] = description
        return client.post("/transactions", json=body)
    return _tx


def balance_of(client, account_id) -> str:
    return client.get(f"/accounts/{account_id}/balance").json()["balance"]
