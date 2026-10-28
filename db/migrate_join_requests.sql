-- Requests to join a public collection, from Communities (polish item 10). Apply by hand as doadmin,
-- before deploying the code:
--   psql "$DOADMIN_URI_FOR_tms" -v ON_ERROR_STOP=1 -f db/migrate_join_requests.sql
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS join_requests (
    collection   text NOT NULL REFERENCES collections (slug),
    pubkey       text NOT NULL CHECK (pubkey ~ '^[0-9a-f]{64}$'),
    note         text NOT NULL DEFAULT '' CHECK (char_length(note) <= 280),
    at           timestamptz NOT NULL DEFAULT now(),
    dismissed_by text,
    dismissed_at timestamptz,
    PRIMARY KEY (collection, pubkey)
);
GRANT SELECT, INSERT, UPDATE ON join_requests TO tms;
COMMIT;
