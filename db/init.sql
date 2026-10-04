-- ============================================================================
-- TMS v2 — L0 Ledger schema (PostgreSQL)
--
-- Substrate for the number-free truth maintenance system described in
-- V1.md. This is L0 only: an append-only ledger of opaque text statements.
-- Belief, status, chains — everything epistemic — is derived at query time
-- by L1 (the evaluator, application code). NONE of it is stored here.
--
-- Mapping from V1.md §2 (originally written as a Neo4j property graph):
--
--   Neo4j label / rel        -> this schema
--   -----------------------------------------------
--   (:Source)                -> table `sources`
--   (:Observation)           -> table `observations`
--   `PUBLISHED` Source->Obs  -> FK `observations.source_id`
--   `SAME_AS`   Claim->Claim -> table `same_as`
--   `DUPLICATE_OF`           -> table `duplicate_of`
--   `SUPERSEDES`             -> table `supersedes`
--   `(:Evidence)` node       -> table `evidence` (reified edge, still a row)
--   `FROM`                   -> `evidence.from_observation_id` FK
--   `TARGETS`                -> `evidence.target_*` FKs (one per target kind)
--
-- The reified-evidence rule (§2 note) survives intact: Evidence is a row,
-- so the link itself can be targeted by other evidence (undercutting).
--
-- Discipline enforced here (non-negotiable per §0 / README):
--   * Claims are opaque text. No subject/predicate/object, no entities,
--     no extraction. Interpretation belongs to agents and L2 projections.
--   * Nothing derived is ever stored. There is no `status` column anywhere.
--     `believed` / `disbelieved` / `contested` are query-time results (§3).
--   * Append-only: triggers deny UPDATE and DELETE on every table (§6).
--     Corrections arrive as edges (SUPERSEDES) and new claims.
--   * One clock: `asserted_at` on every row, same name everywhere (§6).
--     Set by the system, never by an agent. (DEFAULT now() is the system.)
--
-- Requirements: PostgreSQL 16+, pgvector >= 0.7 (halfvec indexing) for §5
--   retrieval. Suggested image: pgvector/pgvector:pg18 (or equivalent).
-- Embeddings: Qwen/Qwen3-Embedding-8B — 4096 dims, L2-normalized, Apache-2.0.
--   Column type is vector(4096) (stores up to 16k dims, no problem), but
--   pgvector HNSW indexes cap at 2,000 dims on the vector type, so the
--   indexes below cast to halfvec(4096) (up to 4,000 index dims). Queries
--   must use the same cast: ORDER BY embedding::halfvec(4096) <=> :q::halfvec.
--   embedding_model is stored on every row and is part of the data (§5).
-- Usage: mounted as the container's /docker-entrypoint-initdb.d/init.sql,
-- or applied manually: psql -f db/init.sql
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ===========================================================================
-- 1. SOURCES  (§2)
--    Where an observation came from. REBUTS a Source = undermining (§2).
--    No status, no trust score, no reliability number. Ever. (§1, §3, §8)
-- ---------------------------------------------------------------------------
CREATE TABLE sources (
    id           text        PRIMARY KEY,  -- minted by the server, e.g. 's1'
    name         text        NOT NULL,
    uri          text,
    asserted_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT sources_name_not_empty CHECK (btrim(name) <> '')
);

-- ===========================================================================
-- 2. OBSERVATIONS  (§2)
--    A document: tweet, paper, repo, blog, report. Immutable once written.
--    Integrity is attacked directly via REBUTS-an-Observation evidence.
-- ---------------------------------------------------------------------------
CREATE TABLE observations (
    id              text        PRIMARY KEY,  -- app-minted, e.g. 'o1'
    source_id       text        NOT NULL REFERENCES sources(id),
    uri             text        NOT NULL,
    content         text,                    -- full document text, opaque
    content_hash    text        NOT NULL,    -- e.g. 'sha256:9f3a...'
    asserted_at     timestamptz NOT NULL DEFAULT now(),
    embedding       vector(4096),   -- Qwen3-Embedding-8B native dimension
    embedding_model text,

    -- The hash binds content; integrity is attacked via REBUTS-an-Observation.
    -- Dedup is NOT unique-constrained: identical text at a new uri is a new
    -- observation; dependence is *asserted* via `duplicate_of` (§5).
    CONSTRAINT observations_embedding_model_pinned
        CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);

CREATE INDEX observations_content_hash_idx ON observations (content_hash);
CREATE INDEX observations_source_idx       ON observations (source_id);
-- as_of scoping (§6): every query may be scoped by asserted_at.
CREATE INDEX observations_asserted_at_idx  ON observations (asserted_at);

-- Semantic retrieval over documents ("have we seen this paper?").
-- Semantic retrieval over documents ("have we seen this paper?").
-- vector(4096) exceeds pgvector's 2,000-dim HNSW ceiling on the vector type;
-- index at half precision instead (halfvec supports up to 4,000). Qwen3
-- embeddings are L2-normalized, so the cast loses almost nothing.
CREATE INDEX observations_embedding_hnsw
    ON observations USING hnsw (embedding::halfvec(4096) halfvec_cosine_ops);

-- ===========================================================================
-- 3. CLAIMS  (§2)
--    A statement. The atomic unit. Opaque: the base layer never decomposes it
--    (no subject/predicate/object columns, no entity keys — §0, §5).
--    Text is NOT unique: re-asserting the same words mints a new claim;
--    co-reference is asserted via `same_as` edges, never assumed (§5).
-- ---------------------------------------------------------------------------
CREATE TABLE claims (
    id              text        PRIMARY KEY,   -- e.g. 'c1'
    text            text        NOT NULL CHECK (char_length(text) > 0),
    asserted_at     timestamptz NOT NULL DEFAULT now(),
    embedding       vector(4096),   -- Qwen3-Embedding-8B native dimension
    embedding_model text,
    CONSTRAINT claim_embedding_model_pinned
        CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);

-- Semantic retrieval ("all claims about X") is embedding similarity, never
-- an entity join (§5). Cosine over the pinned model's space; queries are
-- embedded with Qwen3's task instruction prepended, documents without.
-- Index at half precision: vector(4096) exceeds the 2,000-dim HNSW ceiling
-- on vector; halfvec indexes up to 4,000 and is near-lossless here because
-- the embeddings are unit-normalized.
CREATE INDEX claims_embedding_hnsw
    ON claims USING hnsw (embedding::halfvec(4096) halfvec_cosine_ops);
CREATE INDEX claims_asserted_at_idx ON claims (asserted_at);

-- ===========================================================================
-- 4. EVIDENCE  (§2 — the reified edge)
--    An assertion that an observation bears on a target, with a reason.
--    `reason` is the entire payload of the system: plain language, specific,
--    checkable. "Supports weakly" is forbidden by discipline (§2); the
--    schema can only enforce that a reason exists.
--
--    The attack class falls out of what is targeted (classic argumentation,
--    for free) — derived at query time, never stored:
--      REBUTS a Claim        -> rebutting   (attacks the claim itself)
--      REBUTS an Evidence    -> undercutting ("this observation was misread")
--      REBUTS a Source       -> undermining ("this outlet fabricates")
--      REBUTS an Observation -> attacks the document's integrity directly
-- ----------------------------------------------------------------------------
CREATE TABLE evidence (
    id                  text        PRIMARY KEY,   -- e.g. 'e1'
    relation            text        NOT NULL
        CHECK (relation IN ('SUPPORTS', 'REBUTS', 'QUALIFIES')),

    -- FROM: which document grounds this evidence (never null)
    from_observation_id text        NOT NULL REFERENCES observations (id),

    -- TARGETS: what it bears on. Exactly one target column, matching kind.
    target_kind           text        NOT NULL
        CHECK (target_kind IN ('claim', 'evidence', 'source', 'observation')),
    target_claim_id       text REFERENCES claims (id),
    target_evidence_id    text REFERENCES evidence (id),
    target_source_id      text REFERENCES sources (id),
    target_observation_id text REFERENCES observations (id),

    reason        text        NOT NULL CHECK (char_length(btrim(reason)) > 0),
    asserted_at   timestamptz NOT NULL DEFAULT now(),

    -- exactly one target column populated, matching target_kind
    CONSTRAINT target_exactly_one CHECK (
        (target_kind = 'claim'
            AND target_claim_id IS NOT NULL
            AND target_evidence_id     IS NULL
            AND target_source_id       IS NULL
            AND target_observation_id  IS NULL)
     OR (target_kind = 'evidence'
            AND target_evidence_id     IS NOT NULL
            AND target_claim_id        IS NULL
            AND target_source_id       IS NULL
            AND target_observation_id  IS NULL)
     OR (target_kind = 'source'
            AND target_source_id       IS NOT NULL
            AND target_claim_id        IS NULL
            AND target_evidence_id     IS NULL
            AND target_observation_id  IS NULL)
     OR (target_kind = 'observation'
            AND target_observation_id  IS NOT NULL
            AND target_claim_id        IS NULL
            AND target_evidence_id     IS NULL
            AND target_source_id       IS NULL)
    ),

    -- QUALIFIES targets Claims only in v1 (§2).
    CONSTRAINT qualifies_targets_claims_only
        CHECK (relation <> 'QUALIFIES' OR target_kind = 'claim')
);

-- Reads: "what bears on X" (evaluate, why, get_evidence) and
--        "what does observation O ground" (collapse conditions).
CREATE INDEX evidence_by_target_claim       ON evidence (target_claim_id)
    WHERE target_claim_id IS NOT NULL;
CREATE INDEX evidence_by_target_evidence    ON evidence (target_evidence_id)
    WHERE target_evidence_id IS NOT NULL;
CREATE INDEX evidence_by_target_source      ON evidence (target_source_id)
    WHERE target_source_id IS NOT NULL;
CREATE INDEX evidence_by_target_observation ON evidence (target_observation_id)
    WHERE target_observation_id IS NOT NULL;
CREATE INDEX evidence_by_from_observation   ON evidence (from_observation_id);
CREATE INDEX evidence_by_asserted_at        ON evidence (asserted_at);

-- ===========================================================================
-- 5. IDENTITY AND INDEPENDENCE  (§5)
--    Identity is asserted, never assumed. There are NO entity nodes;
--    co-reference is an attackable claim recorded as an edge with a reason.
--    (v1: SAME_AS is not directly attackable; reify into a claim if needed.)
-- ---------------------------------------------------------------------------
CREATE TABLE same_as (
    id           text        PRIMARY KEY,   -- edge id, for traces and paging
    claim_id     text        NOT NULL REFERENCES claims (id),
    same_as_id   text        NOT NULL REFERENCES claims (id),
    reason       text        NOT NULL CHECK (char_length(btrim(reason)) > 0),
    asserted_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT same_as_not_self CHECK (claim_id <> same_as_id)
);

-- Syndication / dependence: o1 is a copy or derivative of o0 (§5).
-- Verdicts use this so syndication is never mistaken for corroboration (§4).
CREATE TABLE duplicate_of (
    id               text        PRIMARY KEY,
    observation_id   text        NOT NULL REFERENCES observations (id),
    duplicate_of_id  text        NOT NULL REFERENCES observations (id),
    reason           text        NOT NULL CHECK (char_length(reason) > 0),
    asserted_at      timestamptz NOT NULL,

    CONSTRAINT duplicate_of_not_self CHECK (observation_id <> duplicate_of_id),
    CONSTRAINT duplicate_of_distinct UNIQUE (observation_id, duplicate_of_id)
);

-- Document versioning: an updated article supersedes the earlier one (§6).
CREATE TABLE supersedes (
    old_observation_id text        NOT NULL REFERENCES observations (id),
    new_observation_id text        NOT NULL REFERENCES observations (id),
    asserted_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT supersedes_not_self
        CHECK (old_observation_id <> new_observation_id),
    -- a document supersedes at most one predecessor; chain, don't diamond
    UNIQUE (new_observation_id)
);

-- ===========================================================================
-- 6. APPEND-ONLY ENFORCEMENT  (§6)
--    "Never edit; supersede or correct via edges." The store enforces what
--    the discipline requires: no UPDATE, no DELETE, no TRUNCATE. Writers
--    append; corrections are new edges and new claims.
-- ---------------------------------------------------------------------------
CREATE FUNCTION deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        '% on % is not permitted: the ledger is append-only (V1 §6). '
        'Supersede or correct via edges; never mutate.',
        TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

-- One denial trigger per table. Statement-level is enough: any UPDATE, DELETE
-- or TRUNCATE is rejected wholesale. Writes are INSERT-only; corrections are
-- new edges and new claims (SUPERSEDES, SAME_AS, new evidence with reasons).
CREATE TRIGGER sources_immutable      BEFORE UPDATE OR DELETE OR TRUNCATE ON sources      FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER observations_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON observations FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER claims_immutable       BEFORE UPDATE OR DELETE OR TRUNCATE ON claims       FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER evidence_immutable     BEFORE UPDATE OR DELETE OR TRUNCATE ON evidence     FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER same_as_immutable      BEFORE UPDATE OR DELETE OR TRUNCATE ON same_as      FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER duplicate_of_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON duplicate_of FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER supersedes_immutable   BEFORE UPDATE OR DELETE OR TRUNCATE ON supersedes   FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();

-- ============================================================================
-- NOTES FOR REVIEWERS
-- ============================================================================
-- * No UNIQUE on claim text: two agents may assert the same words
--   independently; co-reference is a SAME_AS assertion, not an assumption.
-- * No status / score / weight columns exist anywhere. If you are about to
--   add one, re-read §1 and §8: numbers are computed FROM the graph by
--   external layers, and a layer's output is written back as an attackable
--   claim, never as a field here.
-- * `standing` (in get_evidence responses) is a query-time derivation (§3).
--   It is not a column and must never become one.
-- * DUPLICATE_OF edges feed independence counting in verdicts (§4):
--   support.chains can exceed independent_sources; both are reported.
--   (Same-source corroboration is collapsed by joining through PUBLISHED;
--   no DUPLICATE_OF edge is needed for that case — see §9 note.)
-- ============================================================================
