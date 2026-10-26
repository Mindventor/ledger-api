"""Request and response models.

Money is handled as Decimal end to end (never float) and returned as a
string with two decimals, e.g. "150.00", so no precision is lost in JSON.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints, field_validator

# Largest value that fits NUMERIC(18, 2).
MAX_AMOUNT = Decimal("9999999999999999.99")

Money = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _validate_amount(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("amount must be a finite number")
    if value <= 0:
        raise ValueError("amount must be greater than 0")
    if value > MAX_AMOUNT:
        raise ValueError(f"amount must not exceed {MAX_AMOUNT}")
    if value.as_tuple().exponent < -2:
        raise ValueError("amount can have at most 2 decimal places")
    return value


# ---------------------------------------------------------------- requests

class StrictRequest(BaseModel):
    # Unknown fields are rejected, so a client cannot sneak in
    # "balance": 500 when creating an account.
    model_config = ConfigDict(extra="forbid")


class AccountCreate(StrictRequest):
    name: Annotated[NonEmptyStr, StringConstraints(max_length=255)]


class TransactionCreate(StrictRequest):
    account_id: uuid.UUID
    type: Literal["credit", "debit"]
    amount: Decimal
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    reference_id: Annotated[NonEmptyStr, StringConstraints(max_length=100)]

    _check_amount = field_validator("amount")(_validate_amount)


class TransferCreate(StrictRequest):
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    reference_id: Annotated[NonEmptyStr, StringConstraints(max_length=100)]

    _check_amount = field_validator("amount")(_validate_amount)


# --------------------------------------------------------------- responses

class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    balance: Money
    created_at: datetime


class BalanceOut(BaseModel):
    account_id: uuid.UUID
    balance: Money


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    type: Literal["credit", "debit"]
    amount: Money
    description: str | None
    reference_id: str
    transfer_id: uuid.UUID | None = None
    created_at: datetime


class TransactionCreated(BaseModel):
    transaction: TransactionOut
    balance: Money = Field(description="Account balance after this transaction")


class Pagination(BaseModel):
    page: int
    limit: int
    total_records: int
    total_pages: int


class TransactionPage(BaseModel):
    data: list[TransactionOut]
    pagination: Pagination


class TransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Money
    description: str | None
    reference_id: str
    created_at: datetime


class TransferCreated(BaseModel):
    transfer: TransferOut
    from_account_balance: Money
    to_account_balance: Money
