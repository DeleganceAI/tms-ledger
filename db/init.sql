-- TMS v2: a ledger of signed events (EVENTS.md). PostgreSQL 16+ with pgvector.
-- Apply to an empty database with:
--   psql -v ON_ERROR_STOP=1 -f db/init.sql
-- `events` is the only table holding anything signed. The typed tables are views over it.
-- The server checks signatures and access (tms/ledger.py); the database enforces what it
-- can see on its own: shapes, references inside one collection, link quotes, append-only.
-- Full Qwen/Qwen3-Embedding-8B vectors use exact cosine retrieval (<=>); 4096 dimensions
-- exceed the HNSW index limits.

BEGIN;
CREATE EXTENSION IF NOT EXISTS vector;

-- Written by the first accepted event that names a slug; its signer owns it for good.
CREATE TABLE collections (
    slug       text PRIMARY KEY CHECK (slug ~ '^[a-z0-9][a-z0-9_-]*$'),
    owner      text NOT NULL CHECK (owner ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- tags is [] except on profiles, which keep their signed tags verbatim. content is the exact signed string.
CREATE TABLE events (
    id          text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    pubkey      text NOT NULL CHECK (pubkey ~ '^[0-9a-f]{64}$'),
    created_at  bigint NOT NULL,          -- claimed by the signer
    kind        integer NOT NULL CHECK (kind IN (0, 4701, 4702, 4703, 4704, 4705, 4706, 4708, 4709)),
    tags        jsonb NOT NULL DEFAULT '[]' CHECK (kind = 0 OR tags = '[]'::jsonb),
    content     text NOT NULL CHECK (jsonb_typeof(content::jsonb) = 'object'),
    sig         text NOT NULL CHECK (sig ~ '^[0-9a-f]{128}$'),
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),  -- orders the ledger
    collection  text REFERENCES collections(slug),
    CONSTRAINT events_collection_by_kind CHECK ((collection IS NULL) = (kind IN (0, 4706, 4708))),
    CONSTRAINT events_collection_matches CHECK (collection IS NULL OR collection = content::jsonb ->> 'collection')
);

-- ponytail: views re-parse content per row; a stored jsonb column if reads ever get slow.
CREATE VIEW evidence AS
    SELECT id, pubkey, collection, created_at, received_at,
           content::jsonb ->> 'text' AS text, content::jsonb ->> 'url' AS url,
           content::jsonb ->> 'title' AS title, content::jsonb ->> 'source' AS source
    FROM events WHERE kind = 4701;

CREATE VIEW claims AS
    SELECT id, pubkey, collection, created_at, received_at, content::jsonb ->> 'text' AS text
    FROM events WHERE kind = 4702;

CREATE VIEW links AS
    SELECT id, pubkey, collection, created_at, received_at,
           content::jsonb ->> 'from' AS from_id, content::jsonb ->> 'to' AS to_id,
           content::jsonb ->> 'relation' AS relation, content::jsonb ->> 'quote' AS quote,
           content::jsonb ->> 'reason' AS reason
    FROM events WHERE kind = 4703;

CREATE VIEW contradictions AS
    SELECT id, pubkey, collection, created_at, received_at, content::jsonb ->> 'reason' AS reason,
           ARRAY(SELECT jsonb_array_elements_text(content::jsonb -> 'claims')) AS claim_ids
    FROM events WHERE kind = 4704;

CREATE VIEW contradiction_claims AS
    SELECT e.id AS contradiction_id, m.claim_id
    FROM events e, jsonb_array_elements_text(e.content::jsonb -> 'claims') AS m(claim_id)
    WHERE e.kind = 4704;

-- Latest profile per pubkey; every version stays in events.
CREATE VIEW profiles AS
    SELECT DISTINCT ON (pubkey) pubkey, id, received_at,
           content::jsonb ->> 'name' AS name, content::jsonb ->> 'about' AS about,
           content::jsonb ->> 'picture' AS picture
    FROM events WHERE kind = 0 ORDER BY pubkey, received_at DESC, id;

-- Current membership: the owner, plus the latest owner-signed members list.
CREATE VIEW members AS
    SELECT slug AS collection, owner AS pubkey FROM collections
    UNION
    SELECT l.collection, m.pubkey
    FROM (SELECT DISTINCT ON (e.collection) e.collection, e.content
          FROM events e JOIN collections c ON c.slug = e.collection AND c.owner = e.pubkey
          WHERE e.kind = 4705 ORDER BY e.collection, e.received_at DESC, e.id) l,
         jsonb_array_elements_text(l.content::jsonb -> 'members') AS m(pubkey);

-- A collection's topic and visibility: the latest about event its owner signed.
CREATE VIEW collection_about AS
    SELECT DISTINCT ON (e.collection) e.collection, e.content::jsonb ->> 'topic' AS topic,
           (e.content::jsonb ->> 'public')::boolean AS public, e.received_at
    FROM events e JOIN collections c ON c.slug = e.collection AND c.owner = e.pubkey
    WHERE e.kind = 4709 ORDER BY e.collection, e.received_at DESC, e.id;

-- Quote matching forgives case, whitespace, curly quotes, dashes, soft hyphens and fi/fl
-- ligatures (common in pdftotext output). It checks that the citation exists, nothing more.
CREATE FUNCTION normalize_quote(t text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT btrim(regexp_replace(regexp_replace(lower(
        replace(replace(translate(t,
            E'\u2018\u2019\u201a\u201c\u201d\u201e\u2013\u2014\u2010\u2011\u2212\u00a0\u00ad',
            E'\x27\x27\x27\x22\x22\x22-----\x20'),   -- soft hyphen (last) is dropped
        E'\ufb01', 'fi'), E'\ufb02', 'fl')),
        '\s+', ' ', 'g'), '\s*-\s*', '-', 'g'))     -- "word—word" == "word - word"
$$;

-- Acceptance rules 4 and 5 (EVENTS.md section 5): references exist (in the ledger or
-- earlier in the same transaction), have the right kind, stay in the collection; link
-- quotes appear in the grounding evidence.
CREATE FUNCTION check_event_refs() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    c jsonb := NEW.content::jsonb;
    ref record;
    member text;
BEGIN
    IF NEW.kind = 4703 THEN
        SELECT kind, collection, content::jsonb ->> 'text' AS text INTO ref FROM events WHERE id = c ->> 'from';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'link %: from % does not exist', NEW.id, c ->> 'from' USING ERRCODE = '23503';
        END IF;
        IF ref.kind <> 4701 OR ref.collection IS DISTINCT FROM NEW.collection THEN
            RAISE EXCEPTION 'link %: from must be an evidence event in collection %', NEW.id, NEW.collection
                USING ERRCODE = '23514';
        END IF;
        IF normalize_quote(c ->> 'quote') = '' THEN
            RAISE EXCEPTION 'link %: quote is blank after normalisation', NEW.id USING ERRCODE = '23514';
        END IF;
        IF position(normalize_quote(c ->> 'quote') IN normalize_quote(ref.text)) = 0 THEN
            RAISE EXCEPTION 'link %: quote not found verbatim in evidence %', NEW.id, c ->> 'from'
                USING ERRCODE = '23514';
        END IF;
        SELECT kind, collection INTO ref FROM events WHERE id = c ->> 'to';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'link %: to % does not exist', NEW.id, c ->> 'to' USING ERRCODE = '23503';
        END IF;
        IF ref.kind NOT IN (4701, 4702, 4703, 4704) OR ref.collection IS DISTINCT FROM NEW.collection THEN
            RAISE EXCEPTION 'link %: to must be an evidence, claim, link or contradiction in collection %',
                NEW.id, NEW.collection USING ERRCODE = '23514';
        END IF;
        IF c ->> 'relation' = 'QUALIFIES' AND ref.kind <> 4702 THEN
            RAISE EXCEPTION 'link %: QUALIFIES may only target a claim', NEW.id USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.kind = 4704 THEN
        FOR member IN SELECT jsonb_array_elements_text(c -> 'claims') LOOP
            SELECT kind, collection INTO ref FROM events WHERE id = member;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'contradiction %: claim % does not exist', NEW.id, member USING ERRCODE = '23503';
            END IF;
            IF ref.kind <> 4702 OR ref.collection IS DISTINCT FROM NEW.collection THEN
                RAISE EXCEPTION 'contradiction %: % is not a claim in collection %', NEW.id, member, NEW.collection
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER events_refs BEFORE INSERT ON events
    FOR EACH ROW WHEN (NEW.kind IN (4703, 4704)) EXECUTE FUNCTION check_event_refs();

CREATE FUNCTION deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on % is not permitted: the ledger is append-only',
        TG_OP, TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON events
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER collections_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON collections
    FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();

-- Expression indexes match the view expressions, so queries through the views use them.
CREATE INDEX events_collection_idx ON events (collection, kind, received_at, id);
CREATE INDEX events_pubkey_idx ON events (pubkey, kind, received_at);
CREATE INDEX events_received_idx ON events (received_at, id);
CREATE INDEX events_link_from_idx ON events ((content::jsonb ->> 'from')) WHERE kind = 4703;
CREATE INDEX events_link_to_idx ON events ((content::jsonb ->> 'to')) WHERE kind = 4703;
CREATE INDEX events_contradiction_claims_idx ON events USING gin ((content::jsonb -> 'claims')) WHERE kind = 4704;
CREATE INDEX events_text_idx ON events USING gin (to_tsvector('simple', content::jsonb ->> 'text'))
    WHERE kind IN (4701, 4702);

-- Derived, unsigned, and allowed to change: the server embeds claim text after accepting it.
CREATE TABLE embeddings (
    event_id text PRIMARY KEY REFERENCES events(id),
    vector   vector(4096) NOT NULL,
    model    text NOT NULL
);

-- Operational tables, not ledger data.
-- Request IDs seen in the last two minutes: replay protection for signed tool calls.
CREATE TABLE auth_seen (
    id      text PRIMARY KEY,
    seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_seen_at_idx ON auth_seen (seen_at);

-- One row per MCP request the server handled (reads included). Safe to truncate.
CREATE TABLE mcp_calls (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    method     text NOT NULL,      -- initialize, tools/list, tools/call, prompts/get, ...
    tool       text,               -- tool name when method is tools/call
    pubkey     text,               -- the verified signer, when there is one
    collection text,
    ok         boolean NOT NULL,
    error      text,
    ms         integer NOT NULL
);
CREATE INDEX mcp_calls_at_idx ON mcp_calls (at DESC, id DESC);

-- One row per embeddings request, with the tokens the endpoint reported. Safe to truncate.
CREATE TABLE embed_calls (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    pubkey     text,               -- whose publish or search caused it
    collection text,
    model      text NOT NULL,
    tokens     integer NOT NULL,
    cost_usd   numeric(12, 8) NOT NULL
);
CREATE INDEX embed_calls_at_idx ON embed_calls (at DESC);

-- Unsigned requests from the landing page. One pending request per npub. Safe to prune.
CREATE TABLE access_requests (
    id         bigserial PRIMARY KEY,
    npub       text CHECK (npub ~ '^npub1[02-9ac-hj-np-z]{58}$'),
    email      text CHECK (email = lower(email) AND email LIKE '%_@_%'),  -- for people without a Nostr key
    note       text CHECK (char_length(note) <= 500),
    at         timestamptz NOT NULL DEFAULT now(),
    status     text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'dismissed')),
    decided_by text,               -- the admin's pubkey
    decided_at timestamptz,
    CONSTRAINT access_requests_who CHECK (npub IS NOT NULL OR email IS NOT NULL)
);
CREATE UNIQUE INDEX access_requests_one_pending ON access_requests (npub) WHERE status = 'pending';
CREATE UNIQUE INDEX access_requests_one_pending_email ON access_requests (email) WHERE status = 'pending' AND npub IS NULL;

-- Keys an admin approved in /admin. Access = TMS_ADMINS + TMS_APPROVED (env, bootstrap) + this table.
CREATE TABLE approvals (
    pubkey      text PRIMARY KEY CHECK (pubkey ~ '^[0-9a-f]{64}$'),
    approved_by text NOT NULL,
    at          timestamptz NOT NULL DEFAULT now()
);

-- Admins added in /admin by a site admin (TMS_ADMINS). Same powers as a site admin, except
-- adding and removing admins. Rows are deleted on removal: this is access control, not ledger data.
CREATE TABLE admins (
    pubkey   text PRIMARY KEY CHECK (pubkey ~ '^[0-9a-f]{64}$'),
    added_by text NOT NULL,
    at       timestamptz NOT NULL DEFAULT now()
);

-- Email sign-in (operational, not ledger data). The server generates and holds a Nostr key for
-- each email account, encrypted with TMS_KEY_SECRET, until the user exports it and asks us to
-- forget it (nsec_enc becomes NULL; the account then signs with its own key).
CREATE TABLE email_accounts (
    email       text PRIMARY KEY CHECK (email = lower(email) AND email LIKE '%_@_%'),
    pubkey      text NOT NULL UNIQUE CHECK (pubkey ~ '^[0-9a-f]{64}$'),
    nsec_enc    text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    exported_at timestamptz
);

-- One-time codes, stored hashed. purpose: 'login' or 'export'.
CREATE TABLE email_codes (
    id         bigserial PRIMARY KEY,
    email      text NOT NULL,
    purpose    text NOT NULL CHECK (purpose IN ('login', 'export')),
    code_hash  text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    attempts   integer NOT NULL DEFAULT 0,
    used_at    timestamptz
);
CREATE INDEX email_codes_email_idx ON email_codes (email, purpose, created_at DESC);
COMMIT;
