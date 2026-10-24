-- Move derived embeddings out of the old embeddings table into embedding_index.
-- Does not modify events or any other ledger table.
--
-- Safe to re-run. On a database that already has embedding_index and no embeddings table, this
-- only makes sure the embedding index exists. On a database that still has embeddings, it copies
-- every row (dimensions taken from the stored vector) and drops embeddings only after the copy
-- matches. A failure rolls the whole file back and leaves embeddings in place.
--
-- Deploy, on the direct connection (not the transaction pooler), as a role that can create
-- tables and drop embeddings (doadmin on the managed cluster):
--
--   1. Run this file before the new app starts serving. The new app reads embedding_index only.
--        psql "$DIRECT_URL" -v ON_ERROR_STOP=1 -f db/migrate_embedding_index.sql
--   2. Deploy the app. Claims published while this file holds its lock are stored; their vectors
--      are filled on a later publish (embed_pending). No signed event is rewritten or dropped.
--   3. When a role named tms exists, this file grants it SELECT, INSERT, UPDATE, DELETE on
--      embedding_index (the same rights it had on embeddings). Otherwise grant them yourself.
--
-- Changing EMBED_MODEL afterwards does not touch events. Search uses only the configured model
-- and its dimensions, so vectors from another model stay stored and are never compared with it.
-- To rebuild one model, delete its embedding_index rows (or call ledger.rebuild_embeddings) and
-- let publishes fill them from claim text. The events stay as they are.
--
-- The CREATE TABLE below matches db/init.sql. Keep the two copies the same.

BEGIN;

CREATE TABLE IF NOT EXISTS embedding_index (
    id          bigserial PRIMARY KEY,
    event_id    text NOT NULL REFERENCES events(id),
    model       text NOT NULL CHECK (model <> ''),
    dimensions  integer NOT NULL,
    vector      vector NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT embedding_index_one_per_model UNIQUE (event_id, model),
    CONSTRAINT embedding_index_dims CHECK (dimensions > 0 AND dimensions = vector_dims(vector))
);
CREATE INDEX IF NOT EXISTS embedding_index_lookup_idx ON embedding_index (model, dimensions, event_id);

DO $$
DECLARE
    n_src bigint;
    n_dst bigint;
BEGIN
    IF to_regclass('public.embeddings') IS NULL THEN
        RAISE NOTICE 'no embeddings table; embedding_index left as is';
        RETURN;
    END IF;

    -- Block writes to the old table for the rest of this transaction so the copy cannot miss a row.
    LOCK TABLE embeddings IN ACCESS EXCLUSIVE MODE;

    INSERT INTO embedding_index (event_id, model, dimensions, vector)
    SELECT event_id, model, vector_dims(vector), vector
    FROM embeddings
    ON CONFLICT (event_id, model) DO UPDATE
        SET dimensions = EXCLUDED.dimensions,
            vector = EXCLUDED.vector,
            created_at = now();

    SELECT count(*) INTO n_src FROM embeddings;
    SELECT count(*) INTO n_dst FROM embedding_index i
     WHERE EXISTS (SELECT 1 FROM embeddings e WHERE e.event_id = i.event_id AND e.model = i.model);
    IF n_src IS DISTINCT FROM n_dst THEN
        RAISE EXCEPTION 'embedding migration copied % of % rows; embeddings left in place', n_dst, n_src;
    END IF;
    IF EXISTS (
        SELECT 1 FROM embeddings e
        JOIN embedding_index i ON i.event_id = e.event_id AND i.model = e.model
        WHERE i.dimensions IS DISTINCT FROM vector_dims(e.vector) OR i.vector IS DISTINCT FROM e.vector
    ) THEN
        RAISE EXCEPTION 'embedding migration changed a vector; embeddings left in place';
    END IF;

    DROP TABLE embeddings;
    RAISE NOTICE 'moved % embedding rows into embedding_index and dropped embeddings', n_src;
END;
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tms') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE embedding_index TO tms;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tms;
    END IF;
END;
$$;

COMMIT;
