"""Business rules for accounts, transactions and transfers.

How money stays consistent:
1. Every write runs inside one database transaction (commit all or nothing).
2. Before changing a balance we lock the account row (SELECT ... FOR UPDATE).
   Two requests for the same account therefore run one after the other,
   so the balance check and the balance update can never interleave.
3. reference_id uniqueness is checked under that lock and is also enforced
   by a UNIQUE constraint in the database, in case anything slips through.
4. The database itself rejects negative balances and edits to ledger rows.
"""
import math
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import (
    ApiError,
    AccountNotFound,
    DuplicateTransaction,
    DuplicateTransfer,
    InsufficientBalance,
    InvalidTransfer,
)
from app.models import Account, Transaction, Transfer
from app.schemas import TransactionCreate, TransferCreate, TransactionOut, TransferOut

UNIQUE_VIOLATION = "23505"


def _handle_failure(session: Session, exc: Exception, duplicate: ApiError) -> None:
    """Roll back, then raise `duplicate` for a unique-constraint race, else the original error."""
    session.rollback()
    if isinstance(exc, IntegrityError) and getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
        raise duplicate from exc
    raise exc


# ----------------------------------------------------------------- accounts

def create_account(session: Session, name: str) -> Account:
    # balance is not passed: the column default (0) always applies.
    account = Account(name=name)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def get_account(session: Session, account_id: uuid.UUID) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound(f"Account {account_id} does not exist")
    return account


def _lock_account(session: Session, account_id: uuid.UUID) -> Account:
    """Fetch an account and hold a row lock on it until commit/rollback."""
    account = session.execute(
        select(Account).where(Account.id == account_id).with_for_update()
    ).scalar_one_or_none()
    if account is None:
        raise AccountNotFound(f"Account {account_id} does not exist")
    return account


def _apply(account: Account, tx_type: str, amount: Decimal) -> None:
    if tx_type == "credit":
        account.balance += amount
        return
    if account.balance < amount:
        raise InsufficientBalance(
            "Insufficient balance for this debit",
            {"account_id": str(account.id), "balance": f"{account.balance:.2f}", "requested": f"{amount:.2f}"},
        )
    account.balance -= amount


# ------------------------------------------------------------- transactions

def add_transaction(session: Session, data: TransactionCreate) -> tuple[Transaction, Decimal]:
    try:
        account = _lock_account(session, data.account_id)

        # Duplicate check comes before the balance check on purpose:
        # if a client retries a debit that already went through, it should
        # hear "already exists", not "insufficient balance".
        existing = session.execute(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.reference_id == data.reference_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise DuplicateTransaction(
                "A transaction with this reference_id already exists for this account",
                {"existing_transaction": TransactionOut.model_validate(existing).model_dump(mode="json")},
            )

        _apply(account, data.type, data.amount)
        transaction = Transaction(
            account_id=account.id,
            type=data.type,
            amount=data.amount,
            description=data.description,
            reference_id=data.reference_id,
        )
        session.add(transaction)
        session.flush()  # sends INSERT + balance UPDATE; constraints are checked here
        session.commit()
    except Exception as exc:
        # Any failure (rejected debit, DB error, crash mid-way) leaves no trace.
        _handle_failure(
            session, exc, DuplicateTransaction("A transaction with this reference_id already exists for this account")
        )

    session.refresh(transaction)
    return transaction, account.balance


def list_transactions(
    session: Session,
    account_id: uuid.UUID,
    tx_type: str | None,
    page: int,
    limit: int,
) -> tuple[list[Transaction], int, int]:
    get_account(session, account_id)  # 404 if the account does not exist

    filters = [Transaction.account_id == account_id]
    if tx_type is not None:
        filters.append(Transaction.type == tx_type)

    total = session.execute(select(func.count()).select_from(Transaction).where(*filters)).scalar_one()
    rows = session.execute(
        select(Transaction)
        .where(*filters)
        .order_by(Transaction.created_at.desc(), Transaction.seq.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).scalars().all()
    total_pages = math.ceil(total / limit) if total else 0
    return list(rows), total, total_pages


# ---------------------------------------------------------------- transfers

def transfer(session: Session, data: TransferCreate) -> tuple[Transfer, Decimal, Decimal]:
    if data.from_account_id == data.to_account_id:
        raise InvalidTransfer("Source and destination accounts must be different")

    try:
        # Lock both rows in a fixed order (sorted by id). If transfer A->B and
        # B->A run at the same time, both try to lock the lower id first,
        # so they queue instead of deadlocking.
        ids = sorted([data.from_account_id, data.to_account_id])
        locked = {
            acc.id: acc
            for acc in session.execute(
                select(Account).where(Account.id.in_(ids)).order_by(Account.id).with_for_update()
            ).scalars()
        }
        for account_id in (data.from_account_id, data.to_account_id):
            if account_id not in locked:
                raise AccountNotFound(f"Account {account_id} does not exist")
        source, target = locked[data.from_account_id], locked[data.to_account_id]

        existing = session.execute(
            select(Transfer).where(
                Transfer.from_account_id == source.id,
                Transfer.reference_id == data.reference_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise DuplicateTransfer(
                "A transfer with this reference_id already exists for the source account",
                {"existing_transfer": TransferOut.model_validate(existing).model_dump(mode="json")},
            )

        _apply(source, "debit", data.amount)
        _apply(target, "credit", data.amount)

        record = Transfer(
            from_account_id=source.id,
            to_account_id=target.id,
            amount=data.amount,
            description=data.description,
            reference_id=data.reference_id,
        )
        session.add(record)
        session.flush()  # need record.id for the two ledger entries

        # Each leg is a normal ledger transaction, so balances still equal
        # the sum of each account's transactions.
        session.add_all([
            Transaction(
                account_id=source.id, type="debit", amount=data.amount,
                description=data.description or f"Transfer to {target.id}",
                reference_id=f"transfer:{record.id}:out", transfer_id=record.id,
            ),
            Transaction(
                account_id=target.id, type="credit", amount=data.amount,
                description=data.description or f"Transfer from {source.id}",
                reference_id=f"transfer:{record.id}:in", transfer_id=record.id,
            ),
        ])
        session.flush()
        session.commit()
    except Exception as exc:  # nothing from a failed transfer is kept
        _handle_failure(
            session, exc, DuplicateTransfer("A transfer with this reference_id already exists for the source account")
        )

    session.refresh(record)
    return record, source.balance, target.balance
