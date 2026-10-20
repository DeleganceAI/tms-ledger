-- TMS v2: append-only records, not an evaluator or workflow engine.
-- PostgreSQL 16+ with pgvector. Apply to an empty database with:
--   psql -v ON_ERROR_STOP=1 -f db/init.sql
-- Author identity is separate from document source; the registry is not login/auth.
-- Full Qwen/Qwen3-Embedding-8B vectors use exact cosine retrieval (<=>).
-- No HNSW index: 4096 dimensions exceed its vector/halfvec index limits.

BEGIN;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE authors (
    id          text PRIMARY KEY CHECK (btrim(id) <> ''),
    name        text NOT NULL CHECK (btrim(name) <> ''),
    kind        text NOT NULL CHECK (kind IN ('human', 'agent')),
    asserted_at timestamptz NOT NULL DEFAULT now()
);

-- A collection scopes observations, claims and contradictions (one topic or
-- project). Sources and authors are global. The same document imported into
-- two collections is two observations.
CREATE TABLE collections (
    id          text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9_-]*$'),
    name        text NOT NULL CHECK (btrim(name) <> ''),
    author_id   text NOT NULL REFERENCES authors(id),
    asserted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources (
    id          text PRIMARY KEY,
    name        text NOT NULL CHECK (btrim(name) <> ''),
    uri         text,
    author_id   text NOT NULL REFERENCES authors(id),
    asserted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE observations (
    id              text PRIMARY KEY,
    collection_id   text NOT NULL REFERENCES collections(id),
    source_id       text NOT NULL REFERENCES sources(id),
    uri             text NOT NULL,
    title           text,  -- existing databases: ALTER TABLE observations ADD COLUMN title text;
    content         text,
    content_hash    text NOT NULL,
    author_id       text NOT NULL REFERENCES authors(id),
    asserted_at     timestamptz NOT NULL DEFAULT now(),
    embedding       vector(4096),
    embedding_model text,
    CONSTRAINT observations_embedding_model_pinned
        CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);

-- Matching text or hashes do not merge records or make appends idempotent.
CREATE TABLE claims (
    id              text PRIMARY KEY,
    collection_id   text NOT NULL REFERENCES collections(id),
    text            text NOT NULL CHECK (char_length(text) > 0),
    author_id       text NOT NULL REFERENCES authors(id),
    asserted_at     timestamptz NOT NULL DEFAULT now(),
    embedding       vector(4096),
    embedding_model text,
    CONSTRAINT claim_embedding_model_pinned
        CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);

CREATE TABLE contradictions (
    id            text PRIMARY KEY,
    collection_id text NOT NULL REFERENCES collections(id),
    reason        text NOT NULL CHECK (btrim(reason) <> ''),
    -- Structural cardinality freezes the member set; not a confidence measure.
    -- The append tool supplies the length of its distinct claim_ids list.
    claim_count integer NOT NULL CHECK (claim_count >= 2),
    author_id   text NOT NULL REFERENCES authors(id),
    asserted_at timestamptz NOT NULL DEFAULT now()
);

-- Membership belongs to the finding and inherits its author and timestamp.
CREATE TABLE contradiction_claims (
    contradiction_id text NOT NULL REFERENCES contradictions(id),
    claim_id         text NOT NULL REFERENCES claims(id),
    PRIMARY KEY (contradiction_id, claim_id)
);

CREATE TABLE evidence (
    id                      text PRIMARY KEY,
    relation                text NOT NULL
        CHECK (relation IN ('SUPPORTS', 'REBUTS', 'QUALIFIES')),
    from_observation_id     text NOT NULL REFERENCES observations(id),
    target_kind             text NOT NULL
        CHECK (target_kind IN ('claim', 'contradiction', 'evidence', 'source', 'observation')),
    target_claim_id         text REFERENCES claims(id),
    target_contradiction_id text REFERENCES contradictions(id),
    target_evidence_id      text REFERENCES evidence(id),
    target_source_id        text REFERENCES sources(id),
    target_observation_id   text REFERENCES observations(id),
    -- Verbatim excerpt of the grounding observation; a trigger below rejects
    -- quotes that do not occur in that observation's stored content. The
    -- length cap stops "quoting" a whole document.
    quote                   text NOT NULL
        CHECK (btrim(quote) <> '' AND char_length(quote) <= 1500),
    reason                  text NOT NULL CHECK (btrim(reason) <> ''),
    author_id               text NOT NULL REFERENCES authors(id),
    asserted_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT target_exactly_one CHECK (
        num_nonnulls(target_claim_id, target_contradiction_id, target_evidence_id,
                     target_source_id, target_observation_id) = 1
        AND CASE target_kind
            WHEN 'claim' THEN target_claim_id IS NOT NULL
            WHEN 'contradiction' THEN target_contradiction_id IS NOT NULL
            WHEN 'evidence' THEN target_evidence_id IS NOT NULL
            WHEN 'source' THEN target_source_id IS NOT NULL
            WHEN 'observation' THEN target_observation_id IS NOT NULL
            ELSE false
        END
    ),
    CONSTRAINT qualifies_targets_claims_only
        CHECK (relation <> 'QUALIFIES' OR target_kind = 'claim')
);

-- Insert the finding and its complete membership in ONE transaction.
-- Deferred checks reject incomplete findings at commit and later membership
-- additions: the declared count cannot change and members cannot be removed.
CREATE FUNCTION check_contradiction_members() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    finding_id text;
    expected_count integer;
BEGIN
    IF TG_TABLE_NAME = 'contradictions' THEN
        finding_id := NEW.id;
    ELSE
        finding_id := NEW.contradiction_id;
    END IF;
    SELECT claim_count INTO STRICT expected_count
        FROM contradictions WHERE id = finding_id;
    IF (SELECT count(*) FROM contradiction_claims WHERE contradiction_id = finding_id)
        <> expected_count THEN
        RAISE EXCEPTION 'Contradiction % requires exactly % distinct member claims',
            finding_id, expected_count USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER contradiction_members_complete
    AFTER INSERT ON contradictions DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_contradiction_members();
CREATE CONSTRAINT TRIGGER contradiction_members_frozen
    AFTER INSERT ON contradiction_claims DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_contradiction_members();

-- Citation check: the quote must occur in the grounding observation's text.
-- Normalisation only forgives case, whitespace, curly quotes, dashes, soft
-- hyphens and fi/fl ligatures (common in pdftotext output). It is a check
-- that the citation exists, not a judgement about what it shows.
CREATE FUNCTION normalize_quote(t text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT btrim(regexp_replace(regexp_replace(lower(
        replace(replace(translate(t,
            E'‘’‚“”„–—‐‑− ­',
            E'\x27\x27\x27\x22\x22\x22-----\x20'),   -- soft hyphen (last) is dropped
        E'ﬁ', 'fi'), E'ﬂ', 'fl')),
        '\s+', ' ', 'g'), '\s*-\s*', '-', 'g'))     -- "word—word" == "word - word"
$$;

CREATE FUNCTION check_evidence_quote() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    doc text;
BEGIN
    SELECT content INTO doc FROM observations WHERE id = NEW.from_observation_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Observation % does not exist', NEW.from_observation_id
            USING ERRCODE = '23503';
    END IF;
    IF doc IS NULL THEN
        RAISE EXCEPTION 'Observation % has no stored content, so it cannot ground evidence',
            NEW.from_observation_id USING ERRCODE = '23514';
    END IF;
    IF normalize_quote(NEW.quote) = '' THEN
        RAISE EXCEPTION 'Quote is blank after normalisation' USING ERRCODE = '23514';
    END IF;
    IF position(normalize_quote(NEW.quote) IN normalize_quote(doc)) = 0 THEN
        RAISE EXCEPTION 'Quote not found verbatim in observation %', NEW.from_observation_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER evidence_quote_grounded BEFORE INSERT ON evidence
    FOR EACH ROW EXECUTE FUNCTION check_evidence_quote();

CREATE INDEX collections_author_time_idx ON collections (author_id, asserted_at, id);
CREATE INDEX sources_author_time_idx ON sources (author_id, asserted_at, id);
CREATE INDEX sources_uri_idx ON sources (uri);
CREATE INDEX observations_author_time_idx ON observations (author_id, asserted_at, id);
CREATE INDEX observations_time_idx ON observations (asserted_at, id);
CREATE INDEX observations_collection_idx ON observations (collection_id, asserted_at, id);
CREATE INDEX observations_source_idx ON observations (source_id);
CREATE INDEX observations_uri_idx ON observations (uri);
CREATE INDEX observations_hash_idx ON observations (content_hash);
CREATE INDEX observations_text_idx ON observations USING gin (to_tsvector('simple', coalesce(content, '')));
CREATE INDEX claims_author_time_idx ON claims (author_id, asserted_at, id);
CREATE INDEX claims_time_idx ON claims (asserted_at, id);
CREATE INDEX claims_collection_idx ON claims (collection_id, asserted_at, id);
CREATE INDEX claims_text_idx ON claims USING gin (to_tsvector('simple', text));
CREATE INDEX contradictions_author_time_idx ON contradictions (author_id, asserted_at, id);
CREATE INDEX contradictions_time_idx ON contradictions (asserted_at, id);
CREATE INDEX contradictions_collection_idx ON contradictions (collection_id, asserted_at, id);
CREATE INDEX contradiction_claims_claim_idx ON contradiction_claims (claim_id, contradiction_id);
CREATE INDEX evidence_author_time_idx ON evidence (author_id, asserted_at, id);
CREATE INDEX evidence_time_idx ON evidence (asserted_at, id);
CREATE INDEX evidence_from_idx ON evidence (from_observation_id);
CREATE INDEX evidence_claim_idx ON evidence (target_claim_id) WHERE target_claim_id IS NOT NULL;
CREATE INDEX evidence_contradiction_idx ON evidence (target_contradiction_id) WHERE target_contradiction_id IS NOT NULL;
CREATE INDEX evidence_evidence_idx ON evidence (target_evidence_id) WHERE target_evidence_id IS NOT NULL;
CREATE INDEX evidence_source_idx ON evidence (target_source_id) WHERE target_source_id IS NOT NULL;
CREATE INDEX evidence_observation_idx ON evidence (target_observation_id) WHERE target_observation_id IS NOT NULL;

-- Operational telemetry, not part of the epistemic ledger: one row per MCP
-- request the server handled (reads included). No immutability trigger; it is
-- safe to truncate. The local dashboard (tms-ui) reads it.
CREATE TABLE mcp_calls (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    method      text NOT NULL,      -- initialize, tools/list, tools/call, prompts/get, ...
    tool        text,               -- tool name when method is tools/call
    author_id   text,               -- taken from the call's arguments when present
    collection  text,
    ok          boolean NOT NULL,
    error       text,
    ms          integer NOT NULL
);
CREATE INDEX mcp_calls_at_idx ON mcp_calls (at DESC, id DESC);

CREATE FUNCTION deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not permitted: the ledger is append-only',
        TG_OP, TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER authors_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON authors
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER collections_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON collections
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER sources_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON sources
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER observations_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON observations
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER claims_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON claims
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER contradictions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON contradictions
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER contradiction_claims_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON contradiction_claims
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER evidence_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON evidence
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
COMMIT;
