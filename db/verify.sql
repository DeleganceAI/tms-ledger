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
INSERT INTO sources (id, name, uri, author_id) VALUES
    ('check-source', 'Public filing', 'https://example.org/filings', 'check-human');
INSERT INTO observations (id, source_id, uri, content, content_hash, author_id) VALUES
    ('check-o1', 'check-source', 'https://example.org/2024', 'Alice is CEO in 2024.', 'sha256:check-a', 'check-human'),
    ('check-o2', 'check-source', 'https://example.org/2025', 'Bob is CEO in 2025.', 'sha256:check-b', 'check-agent');
INSERT INTO claims (id, text, author_id) VALUES
    ('check-c1', 'Alice is CEO.', 'check-human'),
    ('check-c2', 'Bob is CEO.', 'check-agent'),
    ('check-c3', 'The company has one CEO.', 'check-agent');
INSERT INTO contradictions (id, reason, claim_count, author_id) VALUES
    ('check-k1', 'Both people cannot be the sole CEO at the same time.', 2, 'check-agent'),
    ('check-k2', 'The three claims cannot all hold at the same time.', 3, 'check-human');
INSERT INTO contradiction_claims (contradiction_id, claim_id) VALUES
    ('check-k1', 'check-c1'), ('check-k1', 'check-c2'),
    ('check-k2', 'check-c1'), ('check-k2', 'check-c2'), ('check-k2', 'check-c3');
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

-- New research, then evidence: no stored resolution or claim-status mutation.
INSERT INTO observations (id, source_id, uri, content, content_hash, author_id) VALUES
    ('check-o3', 'check-source', 'https://example.org/history',
     'The filings name Alice in 2024 and Bob in 2025.', 'sha256:check-c', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_claim_id, reason, author_id) VALUES
    ('check-e1', 'SUPPORTS', 'check-o1', 'claim', 'check-c1', 'The 2024 filing names Alice.', 'check-human'),
    ('check-e2', 'SUPPORTS', 'check-o2', 'claim', 'check-c2', 'The 2025 filing names Bob.', 'check-agent'),
    ('check-q1', 'QUALIFIES', 'check-o3', 'claim', 'check-c1', 'Alice is named for 2024, not all years.', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_contradiction_id, reason, author_id) VALUES
    ('check-e3', 'REBUTS', 'check-o3', 'contradiction', 'check-k1',
     'The documents concern different years, so both claims can hold.', 'check-agent');
-- Existing document, source and evidence-review targets remain available.
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_evidence_id, reason, author_id) VALUES
    ('check-e4', 'REBUTS', 'check-o3', 'evidence', 'check-e1',
     'The wording omits the year given in the filing.', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_observation_id, reason, author_id) VALUES
    ('check-e5', 'SUPPORTS', 'check-o3', 'observation', 'check-o1',
     'The history reproduces the original filing.', 'check-agent');
INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                      target_source_id, reason, author_id) VALUES
    ('check-e6', 'SUPPORTS', 'check-o3', 'source', 'check-source',
     'The archive identifies the publisher of both filings.', 'check-human');

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
END;
$$;

-- These constraints protect immutable membership, including delayed INSERTs.
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradictions (id, reason, claim_count, author_id)
    VALUES ('check-invalid', 'Not a set of claims', 1, 'check-human')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradictions (id, reason, claim_count, author_id)
    VALUES ('check-incomplete', 'No membership supplied', 2, 'check-human')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO contradictions (id, reason, claim_count, author_id)
    VALUES ('check-incomplete', 'Only one member supplied', 2, 'check-human');
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
    INSERT INTO claims (id, text, author_id) VALUES ('check-orphan', 'A claim', 'check-missing-author')
$sql$, '23503');
SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, text) VALUES ('check-anonymous', 'A claim')
$sql$, '23502');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_claim_id, target_contradiction_id, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-o3', 'claim', 'check-c1', 'check-k1', 'Two targets', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-o3', 'claim', 'check-k1', 'Wrong target kind', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, reason, author_id)
    VALUES ('check-invalid', 'QUALIFIES', 'check-o3', 'contradiction', 'check-k1', 'Invalid qualification', 'check-agent')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-missing-document', 'contradiction', 'check-k1', 'Missing grounds', 'check-agent')
$sql$, '23503');
SELECT pg_temp.expect_error($sql$
    INSERT INTO evidence (id, relation, from_observation_id, target_kind,
                          target_contradiction_id, reason, author_id)
    VALUES ('check-invalid', 'REBUTS', 'check-o3', 'contradiction', 'check-k1', '  ', 'check-agent')
$sql$, '23514');

-- All record types reject edits/removals, even statements matching no rows.
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('authors', 'id'), ('sources', 'id'), ('observations', 'id'),
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
INSERT INTO claims (id, text, author_id, embedding, embedding_model) VALUES
    ('check-vector-a', 'Historical filing about Alice', 'check-agent',
     (ARRAY[1::real] || array_fill(0::real, ARRAY[4095]))::vector, 'Qwen/Qwen3-Embedding-8B'),
    ('check-vector-b', 'Historical filing about Bob', 'check-agent',
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
    INSERT INTO claims (id, text, author_id, embedding_model)
    VALUES ('check-invalid', 'Missing vector', 'check-agent', 'Qwen/Qwen3-Embedding-8B')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO claims (id, text, author_id, embedding, embedding_model)
    VALUES ('check-invalid', 'Wrong dimensions', 'check-agent', '[1,0]'::vector, 'Qwen/Qwen3-Embedding-8B')
$sql$, '22000');

SET CONSTRAINTS ALL IMMEDIATE;
ROLLBACK;
\echo 'PASS: ledger provenance, immutable findings, evidence references, mutation guards, and retrieval'
