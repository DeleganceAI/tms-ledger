-- Open sign-up (ACCOUNTS.md step 2). Apply by hand as doadmin, before deploying the code:
--   psql "$DOADMIN_URI_FOR_tms" -v ON_ERROR_STOP=1 -f db/migrate_signups.sql
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS signups (
    pubkey text PRIMARY KEY CHECK (pubkey ~ '^[0-9a-f]{64}$'),
    at     timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON signups TO tms;
COMMIT;
