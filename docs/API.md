# API Documentation

Base URL (local): `http://localhost:8000`
Interactive docs (Swagger UI): `http://localhost:8000/docs` · OpenAPI JSON: `/openapi.json`

All requests and responses are JSON. Money amounts are returned as strings with two decimals.

| Method | Path | Purpose |
|---|---|---|
| POST | `/accounts` | Create an account |
| GET | `/accounts/{account_id}` | Get an account |
| GET | `/accounts/{account_id}/balance` | Get the current balance |
| POST | `/transactions` | Add a credit or debit |
| GET | `/accounts/{account_id}/transactions` | Transaction history (filter, paginate, newest first) |
| POST | `/transfers` | Transfer money between two accounts |
| GET | `/health` | Health check |

There are no endpoints to edit or delete transactions: they are immutable.

---

## Error format

Every error response looks like this:

```json
{
  "error": {
    "code": "ACCOUNT_NOT_FOUND",
    "message": "Account 3f1c2b9e-0000-4000-8000-000000000000 does not exist",
    "details": "optional, depends on the error"
  }
}
```

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Bad body, bad query parameter, malformed JSON, invalid UUID, unknown field. `details` lists `{field, message}` for each problem. |
| 400 | `INVALID_TRANSFER` | Source and destination account are the same |
| 404 | `ACCOUNT_NOT_FOUND` | Account ID is valid but does not exist |
| 409 | `DUPLICATE_TRANSACTION` | `reference_id` already used on this account. `details.existing_transaction` holds the original. |
| 409 | `DUPLICATE_TRANSFER` | `reference_id` already used for a transfer from this source account |
| 422 | `INSUFFICIENT_BALANCE` | Debit/transfer larger than the balance. `details` shows balance and requested amount. |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

---

## POST /accounts

Create an account. The balance always starts at `0.00`.

**Body**

| Field | Type | Rules |
|---|---|---|
| `name` | string | Required, 1–255 characters after trimming |

Any other field (including `balance`) is rejected with 400.

**201 Created**

```json
{
  "id": "2048cb52-7fae-4637-a89f-7a9934083307",
  "name": "Asha",
  "balance": "0.00",
  "created_at": "2026-10-26T14:36:01.370911Z"
}
```

---

## GET /accounts/{account_id}

Returns the account in the same shape as above. **404** if it does not exist, **400** if the ID is not a UUID.

---

## GET /accounts/{account_id}/balance

**200 OK**

```json
{ "account_id": "2048cb52-7fae-4637-a89f-7a9934083307", "balance": "70.00" }
```

**404** `ACCOUNT_NOT_FOUND` · **400** `VALIDATION_ERROR` for a malformed ID.

---

## POST /transactions

Add a credit or debit to an account. The transaction row and the balance change are saved together, or not at all.

**Body**

| Field | Type | Rules |
|---|---|---|
| `account_id` | UUID | Required, account must exist |
| `type` | string | Required, `credit` or `debit` |
| `amount` | number or numeric string | Required, > 0, max 2 decimal places |
| `description` | string | Optional, max 500 characters |
| `reference_id` | string | Required, 1–100 characters, unique per account |

**Example**

```json
{
  "account_id": "2048cb52-7fae-4637-a89f-7a9934083307",
  "type": "debit",
  "amount": 30,
  "description": "Groceries",
  "reference_id": "grocery-1"
}
```

**201 Created** (includes the balance after the transaction)

```json
{
  "transaction": {
    "id": "e7ef334b-f95a-4004-a13c-bc2429cef2e2",
    "account_id": "2048cb52-7fae-4637-a89f-7a9934083307",
    "type": "debit",
    "amount": "30.00",
    "description": "Groceries",
    "reference_id": "grocery-1",
    "transfer_id": null,
    "created_at": "2026-10-26T14:36:01.401767Z"
  },
  "balance": "70.00"
}
```

**422 Insufficient balance** (nothing is saved, balance unchanged)

```json
{
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Insufficient balance for this debit",
    "details": { "account_id": "2048cb52-...", "balance": "70.00", "requested": "150.00" }
  }
}
```

**409 Duplicate reference_id** (nothing is created, balance unchanged)

```json
{
  "error": {
    "code": "DUPLICATE_TRANSACTION",
    "message": "A transaction with this reference_id already exists for this account",
    "details": { "existing_transaction": { "id": "e7ef334b-...", "reference_id": "grocery-1", "amount": "30.00", "...": "..." } }
  }
}
```

**400 Validation error**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      { "field": "type", "message": "Input should be 'credit' or 'debit'" },
      { "field": "amount", "message": "amount must be greater than 0" },
      { "field": "reference_id", "message": "Field required" }
    ]
  }
}
```

**404** `ACCOUNT_NOT_FOUND` if `account_id` does not exist.

---

## GET /accounts/{account_id}/transactions

Transaction history for one account, newest first.

**Query parameters**

| Param | Default | Rules |
|---|---|---|
| `type` | (both) | `credit` or `debit`. Leave it out to get both. |
| `page` | 1 | Integer ≥ 1 |
| `limit` | 20 | Integer 1–100 |

**200 OK**

```json
{
  "data": [
    {
      "id": "e7ef334b-f95a-4004-a13c-bc2429cef2e2",
      "account_id": "2048cb52-7fae-4637-a89f-7a9934083307",
      "type": "debit",
      "amount": "30.00",
      "description": "Groceries",
      "reference_id": "grocery-1",
      "transfer_id": null,
      "created_at": "2026-10-26T14:36:01.401767Z"
    },
    {
      "id": "93e85f94-6cf9-4a8f-9557-54526ae7df1a",
      "account_id": "2048cb52-7fae-4637-a89f-7a9934083307",
      "type": "credit",
      "amount": "100.00",
      "description": "Salary",
      "reference_id": "sal-oct",
      "transfer_id": null,
      "created_at": "2026-10-26T14:36:01.392444Z"
    }
  ],
  "pagination": { "page": 1, "limit": 2, "total_records": 2, "total_pages": 1 }
}
```

A page past the end returns `"data": []` with the same pagination totals.
**400** for invalid `page`, `limit` or `type` · **404** if the account does not exist.

---

## POST /transfers

Move money from one account to another. The debit and the credit happen in one database transaction: if any part fails, nothing changes.

**Body**

| Field | Type | Rules |
|---|---|---|
| `from_account_id` | UUID | Required, must exist |
| `to_account_id` | UUID | Required, must exist, different from source |
| `amount` | number or numeric string | Required, > 0, max 2 decimal places |
| `description` | string | Optional |
| `reference_id` | string | Required, unique per source account |

**201 Created**

```json
{
  "transfer": {
    "id": "6b551c7d-77ed-4cf0-9bb4-b82a468fd29a",
    "from_account_id": "2048cb52-7fae-4637-a89f-7a9934083307",
    "to_account_id": "8f22e856-be81-47b4-a45e-270e176e142f",
    "amount": "20.00",
    "description": "Dinner split",
    "reference_id": "split-1",
    "created_at": "2026-10-26T14:36:01.451239Z"
  },
  "from_account_balance": "50.00",
  "to_account_balance": "20.00"
}
```

Each transfer also appears in both accounts' histories as a normal debit/credit with the same `transfer_id`.

**Errors:** 400 `INVALID_TRANSFER` (same account) or `VALIDATION_ERROR` · 404 `ACCOUNT_NOT_FOUND` · 409 `DUPLICATE_TRANSFER` · 422 `INSUFFICIENT_BALANCE`.
