-- For running without Docker. Run as a Postgres superuser:
--   psql -U postgres -f scripts/setup_local_db.sql
CREATE USER ledger WITH PASSWORD 'ledger';
CREATE DATABASE ledger OWNER ledger;
CREATE DATABASE ledger_test OWNER ledger;
