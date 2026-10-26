# Transaction Ledger API

A backend API for a simple ledger: create accounts, post credit and debit
transactions, read balances and paginated history, and transfer money
between accounts.

Built with **Python 3.10+, FastAPI, SQLAlchemy 2 and PostgreSQL**.

- API documentation: [`docs/API.md`](docs/API.md) (interactive Swagger UI at `/docs` once running)
- Assumptions: [`ASSUMPTIONS.md`](ASSUMPTIONS.md)

---

## Run it

### Option A: Docker (easiest)

```bash
docker compose up --build
```

The API is at http://localhost:8000 and Swagger UI at http://localhost:8000/docs.
Tables are created automatically on startup.

### Option B: Local Python + your own PostgreSQL

1. Create the database user and databases (once):

   ```bash
   psql -U postgres -f scripts/setup_local_db.sql
   ```

2. Install and start:

   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements-dev.txt
   uvicorn app.main:app --reload
   ```

The app connects to `postgresql+psycopg://ledger:ledger@localhost:5432/ledger`
by default. To use another database, set `DATABASE_URL` (see `.env.example`).

### Run the tests

The tests need PostgreSQL. They use a separate `ledger_test` database and wipe it between tests.

```bash
# with Docker: start only the database, then run tests on your machine
docker compose up -d db
pip install -r requirements-dev.txt
pytest -q
```

To point the tests at a different database, set `TEST_DATABASE_URL`.

---

## Quick tour (curl)

```bash
# create an account
curl -s -X POST localhost:8000/accounts -H 'content-type: application/json' \
  -d '{"name": "Asha"}'
# -> {"id": "<ACCOUNT_ID>", "name": "Asha", "balance": "0.00", ...}

# credit 100
curl -s -X POST localhost:8000/transactions -H 'content-type: application/json' \
  -d '{"account_id": "<ACCOUNT_ID>", "type": "credit", "amount": 100, "description": "salary", "reference_id": "sal-oct"}'

# debit 30
curl -s -X POST localhost:8000/transactions -H 'content-type: application/json' \
  -d '{"account_id": "<ACCOUNT_ID>", "type": "debit", "amount": 30, "description": "groceries", "reference_id": "grocery-1"}'

# balance and history
curl -s localhost:8000/accounts/<ACCOUNT_ID>/balance
curl -s "localhost:8000/accounts/<ACCOUNT_ID>/transactions?type=debit&page=1&limit=10"
```

---

## Project layout

```
app/
  main.py            FastAPI app, startup migration, router wiring
  config.py          settings (DATABASE_URL, page size limits)
  database.py        engine, session per request, migration runner
  models.py          ORM mappings
  schemas.py         request/response models and input validation
  errors.py          error types and the single JSON error format
  services/ledger.py business rules (locking, idempotency, transfers)
  routers/           HTTP routes
migrations/001_init.sql   tables, constraints, indexes, immutability trigger
tests/                    pytest suite (runs against real PostgreSQL)
```

---

## How data integrity is handled

| Requirement | How it is enforced |
|---|---|
| Initial balance is 0 and cannot be set | `balance` has a DB default of 0. Request models reject unknown fields, so sending `balance` returns 400. |
| Debit cannot exceed balance | Checked in the service while the account row is locked. A `CHECK (balance >= 0)` constraint in the database is the backstop. |
| Atomic balance update | The transaction insert and the balance update run in one database transaction. Any error rolls back both. |
| Concurrent requests | The account row is locked with `SELECT ... FOR UPDATE`, so requests on the same account run one at a time. Without the lock, parallel debits overwrite each other's balance updates (a lost update); the test suite has a test that fails in that case. |
| Duplicate `reference_id` | Checked under the lock and returns 409 with the existing transaction. `UNIQUE (account_id, reference_id)` in the database also enforces it. The same reference can be used on different accounts. |
| Transactions are immutable | No update/delete endpoints. A database trigger also blocks `UPDATE`/`DELETE` on `transactions` and `transfers`. |
| Balance equals sum of valid transactions | Only the service changes balances, always together with a ledger row in the same commit. Rejected requests write nothing. Transfers are recorded as a debit and a credit, so the rule still holds. |
| Transfers are all-or-nothing | Both accounts are locked (in sorted id order to avoid deadlocks), both legs are written, then one commit. |
| Money precision | `NUMERIC(18,2)` in the database, `Decimal` in Python, returned as strings like `"150.00"`. No floats. |

## Status codes

| Code | When |
|---|---|
| 200 | Successful read |
| 201 | Account, transaction or transfer created |
| 400 | `VALIDATION_ERROR` (bad body, bad query params, malformed JSON, invalid UUID) or `INVALID_TRANSFER` (same source and destination) |
| 404 | `ACCOUNT_NOT_FOUND` |
| 409 | `DUPLICATE_TRANSACTION` / `DUPLICATE_TRANSFER` |
| 422 | `INSUFFICIENT_BALANCE` |

Every error has the same shape:

```json
{"error": {"code": "INSUFFICIENT_BALANCE", "message": "Insufficient balance for this debit",
           "details": {"account_id": "...", "balance": "100.00", "requested": "150.00"}}}
```

## Tests

86 tests cover every rule in the brief, including:

- the example sequence from the brief (0 → +100 → +50 → −30 → −20 = 100)
- duplicate references (same and different accounts, retried debit after balance hits 0)
- validation edge cases (zero, negative, 3 decimal places, NaN, wrong types, extra fields)
- history ordering, filtering and pagination metadata
- immutability enforced by the database trigger
- rollback when a failure happens mid-write (single transaction and transfer)
- concurrency: 25 parallel debits on a balance of 100 (exactly 10 succeed), 15 parallel requests with the same reference (exactly 1 succeeds), 30 opposing transfers between two accounts (no deadlock, total conserved)
