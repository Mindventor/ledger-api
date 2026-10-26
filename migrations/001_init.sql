-- Transaction Ledger schema (PostgreSQL 13+)
-- Safe to run more than once: the app applies it on startup.

-- ---------------------------------------------------------------------------
-- Accounts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255)   NOT NULL CHECK (length(btrim(name)) > 0),
    -- Every account starts at 0. The API never accepts a balance from the client.
    balance     NUMERIC(18, 2) NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
    -- Last line of defence: even if application code had a bug,
    -- the database refuses to store a negative balance.
    CONSTRAINT accounts_balance_non_negative CHECK (balance >= 0)
);

-- ---------------------------------------------------------------------------
-- Transfers (bonus feature)
-- One row per transfer; the money movement itself is recorded as two
-- ledger transactions (a debit and a credit) that point back here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transfers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_account_id  UUID           NOT NULL REFERENCES accounts (id),
    to_account_id    UUID           NOT NULL REFERENCES accounts (id),
    amount           NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    reference_id     VARCHAR(100)   NOT NULL CHECK (length(btrim(reference_id)) > 0),
    description      VARCHAR(500),
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT transfers_distinct_accounts CHECK (from_account_id <> to_account_id),
    -- A retried transfer request (same source account + reference) is a duplicate.
    CONSTRAINT transfers_from_reference_unique UNIQUE (from_account_id, reference_id)
);

-- ---------------------------------------------------------------------------
-- Transactions (the ledger)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Insertion order. Used only to break ties when two rows share a timestamp.
    seq           BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    account_id    UUID           NOT NULL REFERENCES accounts (id),
    type          VARCHAR(6)     NOT NULL CHECK (type IN ('credit', 'debit')),
    amount        NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    description   VARCHAR(500),
    reference_id  VARCHAR(100)   NOT NULL CHECK (length(btrim(reference_id)) > 0),
    transfer_id   UUID           REFERENCES transfers (id),
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
    -- reference_id is unique per account, not globally:
    -- two different accounts may reuse the same reference.
    CONSTRAINT transactions_account_reference_unique UNIQUE (account_id, reference_id)
);

-- History queries filter by account (and optionally type) and sort newest first.
CREATE INDEX IF NOT EXISTS idx_transactions_account_created
    ON transactions (account_id, created_at DESC, seq DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_account_type_created
    ON transactions (account_id, type, created_at DESC, seq DESC);

-- ---------------------------------------------------------------------------
-- Immutability: ledger rows can be inserted, never changed or removed.
-- The API exposes no update/delete routes; this trigger also blocks
-- anyone editing rows directly in the database.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION forbid_ledger_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Ledger rows in table "%" are immutable (% not allowed)',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS transactions_immutable ON transactions;
CREATE TRIGGER transactions_immutable
    BEFORE UPDATE OR DELETE ON transactions
    FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

DROP TRIGGER IF EXISTS transfers_immutable ON transfers;
CREATE TRIGGER transfers_immutable
    BEFORE UPDATE OR DELETE ON transfers
    FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();
