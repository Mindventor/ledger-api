import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ledger:ledger@localhost:5432/ledger",
)

# Pagination limits for the transaction history endpoint.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
