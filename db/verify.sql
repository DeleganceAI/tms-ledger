-- Run after init.sql: psql -v ON_ERROR_STOP=1 -f db/verify.sql
-- Real append/research/correction scenario and integrity regressions.
-- All test records and helpers roll back; no server or model download required.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL plpgsql.check_asserts = on;

CREATE FUNCTION pg_temp.expect_error(command text, expected_state text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE command;
        SET CONSTRAINTS ALL IMMEDIATE;
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE = expected_state THEN
            RETURN;
        END IF;
        RAISE;
    END;
    RAISE EXCEPTION 'Expected SQLSTATE %, but command succeeded: %', expected_state, command;
END;
$$;

INSERT INTO authors (id, name, kind) VALUES
    ('check-human', 'Human contributor', 'human'),
    ('check-agent', 'Evidence reader', 'agent');
INSERT INTO collections (id, name, author_id) VALUES
    ('check-col', 'Leadership filings', 'check-human');
INSERT INTO sources (id, name, uri, author_id) VALUES
    ('check-source', 'Public filing', 'https://example.org/filings', 'check-human');
INSERT INTO observations (id, collection_id, source_id, uri, content, content_hash, author_id) VALUES
    ('check-o1', 'check-col', 'check-source', 'https://example.org/2024', 'Alice is CEO in 2024.', 'sha256:check-a', 'check-human'),
    ('check-o2', 'check-col', 'check-source', 'https://example.org/2025', 'Bob is CEO in 2025.', 'sha256:check-b', 'check-agent'),
    ('check-o4', 'check-col', 'check-source', 'https://example.org/pdf',
     E'The “DAO”  enzyme—see ﬁgure 2. IL‑6 and TNF‐alpha rose.', 'sha256:check-d', 'check-agent'),
    ('check-o5', 'check-col', 'check-source', 'https://example.org/lost', NULL, 'sha256:check-e', 'check-agent');
INSERT INTO claims (id, collection_id, text, author_id) VALUES
    ('check-c1', 'check-col', 'Alice is CEO.', 'check-human'),
    ('check-c2', 'check-col', 'Bob is CEO.', 'check-agent'),
    ('check-c3', 'check-col', 'The company has one CEO.', 'check-agent');
INSERT INTO contradictions (id, collection_id, reason, claim_count, author_id) VALUES
    ('check-k1', 'check-col', 'Both people cannot be the sole CEO at the same time.', 2, 'check-agent'),
    ('check-k2', 'check-col', 'The three claims cannot all hold at the same time.', 3, 'check-human');
INSERT INTO contradiction_claims (contradiction_id, claim_id) VALUES
    ('check-k1', 'check-c1'), ('check-k1', 'check-c2'),
    ('check-k2', 'check-c1'), ('check-k2', 'check-c2'), ('check-k2', 'check-c3');
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

-- New research, then evidence: no stored resolution or claim-status mutation.
INSERT INTO observations (id, collection_id, source_id, uri, content, content_hash, author_id) VALUES
    ('check-o3', 'check-col', 'check-source', 'https://example.org/history',
     'The filings name Alice in 2024 and Bob in 2025.', 'sha256:check-c', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_claim_id, quote, reason, author_id) VALUES
    ('check-e1', 'SUPPORTS', 'check-o1', 'claim', 'check-c1', 'Alice is CEO in 2024', 'The 2024 filing names Alice.', 'check-human'),
    ('check-e2', 'SUPPORTS', 'check-o2', 'claim', 'check-c2', 'Bob is CEO in 2025', 'The 2025 filing names Bob.', 'check-agent'),
    ('check-q1', 'QUALIFIES', 'check-o3', 'claim', 'check-c1', 'Alice in 2024', 'Alice is named for 2024, not all years.', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_contradiction_id, quote, reason, author_id) VALUES
    ('check-e3', 'REBUTS', 'check-o3', 'contradiction', 'check-k1', 'Alice in 2024 and Bob in 2025',
     'The documents concern different years, so both claims can hold.', 'check-agent');
-- Existing document, source and evidence-review targets remain available.
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_evidence_id, quote, reason, author_id) VALUES
    ('check-e4', 'REBUTS', 'check-o3', 'evidence', 'check-e1', 'name Alice in 2024',
     'The wording omits the year given in the filing.', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_observation_id, quote, reason, author_id) VALUES
    ('check-e5', 'SUPPORTS', 'check-o3', 'observation', 'check-o1', 'The filings name Alice',
     'The history reproduces the original filing.', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_source_id, quote, reason, author_id) VALUES
    ('check-e6', 'SUPPORTS', 'check-o3', 'source', 'check-source', 'The filings',
     'The archive identifies the publisher of both filings.', 'check-human');
-- Quote matching forgives case, whitespace, curly quotes, dashes, ligatures.
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_claim_id, quote, reason, author_id) VALUES
    ('check-e7', 'SUPPORTS', 'check-o4', 'claim', 'check-c3', 'the "dao" enzyme - see figure 2',
     'Typographic variants of the same passage still cite it.', 'check-agent'),
    ('check-e8', 'SUPPORTS', 'check-o4', 'claim', 'check-c3', 'IL-6 and TNF-alpha',
     'ASCII hyphens match the non-breaking hyphens in the document.', 'check-agent');

DO $$
BEGIN
    ASSERT (SELECT array_agg(c.text ORDER BY c.id)
        FROM contradiction_claims m JOIN claims c ON c.id = m.claim_id
        WHERE m.contradiction_id = 'check-k1') = ARRAY['Alice is CEO.', 'Bob is CEO.'],
        'The original claims must remain discoverable through the finding';
    ASSERT EXISTS (
        SELECT 1 FROM evidence e
        JOIN observations o ON o.id = e.from_observation_id
        JOIN authors a ON a.id = e.author_id
        JOIN sources s ON s.id = o.source_id
        WHERE e.target_contradiction_id = 'check-k1'
          AND e.relation = 'REBUTS' AND o.id = 'check-o3'
          AND a.kind = 'agent' AND s.name = 'Public filing'
          AND e.reason = 'The documents concern different years, so both claims can hold.'
    ), 'A reader must be able to inspect correction grounds, author, and source';
    ASSERT (SELECT reason FROM contradictions WHERE id = 'check-k1') =
        'Both people cannot be the sole CEO at the same time.',
        'Correction evidence must not rewrite the original finding';
    ASSERT (SELECT count(*) FROM claims WHERE collection_id = 'check-col') = 3,
        'Claims are scoped to their collection';
END;
$$;

-- Evidence must quote its grounding observation.
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind, target_claim_id, quote, reason, author_id)
    VALUES ('check-invalid', 'SUPPORTS', 'check-o3', 'claim', 'check-c2', 'Carol is CEO', 'Invented passage', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind, target_claim_id, quote, reason, author_id)
    VALUES ('check-invalid', 'SUPPORTS', 'check-o5', 'claim', 'check-c2', 'anything', 'No content to cite', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind, target_claim_id, quote, reason, author_id)
    VALUES ('check-invalid', 'SUPPORTS', 'check-o3', 'claim', 'check-c2', '   ', 'Blank quote', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind, target_claim_id, quote, reason, author_id)
    VALUES ('check-invalid', 'SUPPORTS', 'check-o3', 'claim', 'check-c2', E'\n\t­', 'Whitespace-only quote', 'check-agent')
$sql$, '23514');

-- Collections are required, must exist, and are immutable like everything else.
SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, text, author_id) VALUES ('check-nocol', 'A claim', 'check-human')
$sql$, '23502');
SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, collection_id, text, author_id) VALUES ('check-badcol', 'check-missing', 'A claim', 'check-human')
$sql$, '23503');
SELECT pg_temp.expect_error($sql$
    INSERT INTO collections (id, name, author_id) VALUES ('Bad Slug', 'Spaces and caps', 'check-human')
$sql$, '23514');

-- These constraints protect immutable membership, including delayed INSERTs.
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradictions (id, collection_id, reason, claim_count, author_id)
    VALUES ('check-invalid', 'check-col', 'Not a set of claims', 1, 'check-human')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradictions (id, collection_id, reason, claim_count, author_id)
    VALUES ('check-incomplete', 'check-col', 'No membership supplied', 2, 'check-human')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradictions (id, collection_id, reason, claim_count, author_id)
    VALUES ('check-incomplete', 'check-col', 'Only one member supplied', 2, 'check-human');
    INSERT INTO contradiction_claims VALUES ('check-incomplete', 'check-c1')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradiction_claims VALUES ('check-k1', 'check-c1')
$sql$, '23505');
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradiction_claims VALUES ('check-k1', 'check-c3')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradiction_claims VALUES ('check-k1', 'check-missing')
$sql$, '23503');

SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, collection_id, text, author_id) VALUES ('check-orphan', 'check-col', 'A claim', 'check-missing-author')
$sql$, '23503');
SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, collection_id, text) VALUES ('check-anonymous', 'check-col', 'A claim')
$sql$, '23502');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_claim_id, target_contradiction_id, quote, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-o3', 'claim', 'check-c1', 'check-k1', 'The filings', 'Two targets', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, quote, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-o3', 'claim', 'check-k1', 'The filings', 'Wrong target kind', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, quote, reason, author_id)
    VALUES ('check-invalid', 'QUALIFIES', 'check-o3', 'contradiction', 'check-k1', 'The filings', 'Invalid qualification', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, quote, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-missing-document', 'contradiction', 'check-k1', 'x', 'Missing grounds', 'check-agent')
$sql$, '23503');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, quote, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-o3', 'contradiction', 'check-k1', 'The filings', '  ', 'check-agent')
$sql$, '23514');

-- All record types reject edits/removals, even statements matching no rows.
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('authors', 'id'), ('collections', 'id'), ('sources', 'id'), ('observations', 'id'),
        ('claims', 'id'), ('contradictions', 'id'),
        ('contradiction_claims', 'claim_id'), ('evidence', 'id')
    ) AS t(table_name, column_name)
    LOOP
        PERFORM pg_temp.expect_error(format('UPDATE %I SET %I = %I WHERE false',
            item.table_name, item.column_name, item.column_name), '55000');
        PERFORM pg_temp.expect_error(format('DELETE FROM %I WHERE false', item.table_name), '55000');
        PERFORM pg_temp.expect_error(format('TRUNCATE %I CASCADE', item.table_name), '55000');
    END LOOP;
END;
$$;

-- Full-dimensional vectors work without halfvec/HNSW. Distances are retrieval,
-- not conclusions. Orthogonal basis vectors make this check deterministic.
INSERT INTO claims (id, collection_id, text, author_id, embedding, embedding_model) VALUES
    ('check-vector-a', 'check-col', 'Historical filing about Alice', 'check-agent',
     (ARRAY[1::real] || array_fill(0::real, ARRAY[4095]))::vector, 'Qwen/Qwen3-Embedding-8B'),
    ('check-vector-b', 'check-col', 'Historical filing about Bob', 'check-agent',
     (ARRAY[0::real, 1::real] || array_fill(0::real, ARRAY[4094]))::vector, 'Qwen/Qwen3-Embedding-8B');
DO $$
BEGIN
    ASSERT (SELECT id FROM claims WHERE id IN ('check-vector-a', 'check-vector-b')
        ORDER BY embedding <=> (ARRAY[1::real] || array_fill(0::real, ARRAY[4095]))::vector, id
        LIMIT 1) = 'check-vector-a', 'Exact cosine retrieval must preserve all 4096 dimensions';
    ASSERT (SELECT array_agg(id ORDER BY id) FROM observations
        WHERE id LIKE 'check-%' AND to_tsvector('simple', coalesce(content, '')) @@ plainto_tsquery('simple', 'Bob'))
        = ARRAY['check-o2', 'check-o3'], 'Keyword retrieval must find original and follow-up content';
END;
$$;
SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, collection_id, text, author_id, embedding_model)
    VALUES ('check-invalid', 'check-col', 'Missing vector', 'check-agent', 'Qwen/Qwen3-Embedding-8B')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, collection_id, text, author_id, embedding, embedding_model)
    VALUES ('check-invalid', 'check-col', 'Wrong dimensions', 'check-agent', '[1,0]'::vector, 'Qwen/Qwen3-Embedding-8B')
$sql$, '22000');

SET CONSTRAINTS ALL IMMEDIATE;
ROLLBACK;
\echo 'PASS: ledger provenance, collections, quoted evidence, immutable findings, mutation guards, and retrieval'
