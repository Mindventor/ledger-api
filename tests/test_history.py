import uuid

import pytest


@pytest.fixture
def account_with_history(make_account, tx):
    acc = make_account()
    # 7 credits and 3 debits, created in this order
    for i in range(7):
        tx(acc, "credit", 10, f"c{i}")
    for i in range(3):
        tx(acc, "debit", 5, f"d{i}")
    return acc


def test_latest_first(client, account_with_history):
    rows = client.get(f"/accounts/{account_with_history}/transactions?limit=100").json()["data"]
    assert [r["reference_id"] for r in rows] == ["d2", "d1", "d0", "c6", "c5", "c4", "c3", "c2", "c1", "c0"]
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)


def test_no_filter_returns_both_types(client, account_with_history):
    body = client.get(f"/accounts/{account_with_history}/transactions").json()
    assert {r["type"] for r in body["data"]} == {"credit", "debit"}
    assert body["pagination"]["total_records"] == 10


@pytest.mark.parametrize("kind,count", [("credit", 7), ("debit", 3)])
def test_filter_by_type(client, account_with_history, kind, count):
    body = client.get(f"/accounts/{account_with_history}/transactions?type={kind}").json()
    assert body["pagination"]["total_records"] == count
    assert all(r["type"] == kind for r in body["data"])


def test_pagination_metadata(client, account_with_history):
    body = client.get(f"/accounts/{account_with_history}/transactions?page=2&limit=4").json()
    assert body["pagination"] == {"page": 2, "limit": 4, "total_records": 10, "total_pages": 3}
    assert [r["reference_id"] for r in body["data"]] == ["c5", "c4", "c3", "c2"]


def test_last_page_is_partial(client, account_with_history):
    body = client.get(f"/accounts/{account_with_history}/transactions?page=3&limit=4").json()
    assert [r["reference_id"] for r in body["data"]] == ["c1", "c0"]


def test_pages_cover_every_row_once(client, account_with_history):
    seen = []
    for page in (1, 2, 3):
        seen += [r["id"] for r in client.get(f"/accounts/{account_with_history}/transactions?page={page}&limit=4").json()["data"]]
    assert len(seen) == len(set(seen)) == 10


def test_filter_and_pagination_together(client, account_with_history):
    body = client.get(f"/accounts/{account_with_history}/transactions?type=credit&page=2&limit=5").json()
    assert body["pagination"] == {"page": 2, "limit": 5, "total_records": 7, "total_pages": 2}
    assert [r["reference_id"] for r in body["data"]] == ["c1", "c0"]


def test_page_past_the_end_is_empty_not_an_error(client, account_with_history):
    body = client.get(f"/accounts/{account_with_history}/transactions?page=50&limit=4").json()
    assert body["data"] == [] and body["pagination"]["total_pages"] == 3


def test_defaults(client, account_with_history):
    p = client.get(f"/accounts/{account_with_history}/transactions").json()["pagination"]
    assert p["page"] == 1 and p["limit"] == 20


def test_empty_history(client, make_account):
    body = client.get(f"/accounts/{make_account()}/transactions").json()
    assert body == {"data": [], "pagination": {"page": 1, "limit": 20, "total_records": 0, "total_pages": 0}}


@pytest.mark.parametrize("query", ["page=0", "page=-1", "page=abc", "limit=0", "limit=101", "limit=x", "type=refund"])
def test_invalid_query_params(client, account_with_history, query):
    r = client.get(f"/accounts/{account_with_history}/transactions?{query}")
    assert r.status_code == 400, query
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_history_unknown_account(client):
    assert client.get(f"/accounts/{uuid.uuid4()}/transactions").status_code == 404
