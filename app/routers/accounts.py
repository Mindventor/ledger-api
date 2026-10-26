import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database import DB
from app.schemas import (
    AccountCreate,
    AccountOut,
    BalanceOut,
    Pagination,
    TransactionCreate,
    TransactionCreated,
    TransactionOut,
    TransactionPage,
)
from app.services import ledger

router = APIRouter(tags=["accounts & transactions"])

ERRORS = {
    400: {"description": "Validation error"},
    404: {"description": "Account not found"},
}


@router.post("/accounts", status_code=status.HTTP_201_CREATED, response_model=AccountOut, responses={400: ERRORS[400]})
def create_account(body: AccountCreate, db: DB):
    """Create an account. The balance always starts at 0 and cannot be set by the client."""
    return ledger.create_account(db, body.name)


@router.get("/accounts/{account_id}", response_model=AccountOut, responses=ERRORS)
def get_account(account_id: uuid.UUID, db: DB):
    return ledger.get_account(db, account_id)


@router.get("/accounts/{account_id}/balance", response_model=BalanceOut, responses=ERRORS)
def get_balance(account_id: uuid.UUID, db: DB):
    account = ledger.get_account(db, account_id)
    return BalanceOut(account_id=account.id, balance=account.balance)


@router.post(
    "/transactions",
    status_code=status.HTTP_201_CREATED,
    response_model=TransactionCreated,
    responses={
        **ERRORS,
        409: {"description": "Duplicate reference_id for this account; nothing was changed"},
        422: {"description": "Insufficient balance; the debit was rejected"},
    },
)
def add_transaction(body: TransactionCreate, db: DB):
    """Credit or debit an account. Transactions cannot be edited or deleted afterwards."""
    transaction, balance = ledger.add_transaction(db, body)
    return TransactionCreated(transaction=TransactionOut.model_validate(transaction), balance=balance)


@router.get("/accounts/{account_id}/transactions", response_model=TransactionPage, responses=ERRORS)
def list_transactions(
    account_id: uuid.UUID,
    db: DB,
    type: Annotated[Literal["credit", "debit"] | None, Query(description="Leave empty for both")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
):
    """Transaction history, newest first, with optional type filter and pagination."""
    rows, total, total_pages = ledger.list_transactions(db, account_id, type, page, limit)
    return TransactionPage(
        data=[TransactionOut.model_validate(r) for r in rows],
        pagination=Pagination(page=page, limit=limit, total_records=total, total_pages=total_pages),
    )
