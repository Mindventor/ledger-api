from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import apply_migrations
from app.errors import register_error_handlers
from app.routers import accounts, transfers


@asynccontextmanager
async def lifespan(_: FastAPI):
    apply_migrations()  # creates tables, constraints and triggers if missing
    yield


app = FastAPI(
    title="Transaction Ledger API",
    version="1.0.0",
    description="Accounts, credit/debit transactions, balances, history and transfers.",
    lifespan=lifespan,
)
register_error_handlers(app)
app.include_router(accounts.router)
app.include_router(transfers.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
