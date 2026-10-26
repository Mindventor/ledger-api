from fastapi import APIRouter, status

from app.database import DB
from app.schemas import TransferCreate, TransferCreated, TransferOut
from app.services import ledger

router = APIRouter(tags=["transfers"])


@router.post(
    "/transfers",
    status_code=status.HTTP_201_CREATED,
    response_model=TransferCreated,
    responses={
        400: {"description": "Validation error, or source and destination are the same"},
        404: {"description": "Source or destination account not found"},
        409: {"description": "Duplicate reference_id for the source account"},
        422: {"description": "Insufficient balance in the source account"},
    },
)
def create_transfer(body: TransferCreate, db: DB):
    """Move money between two accounts. Either both sides happen or neither does."""
    record, from_balance, to_balance = ledger.transfer(db, body)
    return TransferCreated(
        transfer=TransferOut.model_validate(record),
        from_account_balance=from_balance,
        to_account_balance=to_balance,
    )
