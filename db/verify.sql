-- Run after init.sql: psql -v ON_ERROR_STOP=1 -f db/verify.sql
-- Database-side guards on the event ledger: views, references, link quotes, append-only.
-- Signatures are the server's job, so the events here are unsigned stand-ins.
-- Everything rolls back.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL plpgsql.check_asserts = on;

CREATE FUNCTION pg_temp.expect_error(command text, expected_state text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE command;
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE = expected_state THEN
            RETURN;
        END IF;
        RAISE;
    END;
    RAISE EXCEPTION 'Expected SQLSTATE %, but command succeeded: %', expected_state, command;
END;
$$;

-- An unsigned stand-in event; its id is a hash of the name, so tests refer to events by name.
CREATE FUNCTION pg_temp.ev_id(name text) RETURNS text LANGUAGE sql AS $$
    SELECT encode(sha256(convert_to(name, 'UTF8')), 'hex')
$$;
CREATE FUNCTION pg_temp.ev(name text, kind integer, signer text, content jsonb) RETURNS text
LANGUAGE sql AS $$
    INSERT INTO events (id, pubkey, created_at, kind, content, sig, collection)
    VALUES (pg_temp.ev_id(name), pg_temp.ev_id(signer), 1792454400, kind, content::text,
            repeat('0', 128), content ->> 'collection')
    RETURNING id
$$;
CREATE FUNCTION pg_temp.k(name text) RETURNS text LANGUAGE sql AS $$ SELECT pg_temp.ev_id(name) $$;

INSERT INTO collections (slug, owner) VALUES ('check', pg_temp.ev_id('owner')), ('other', pg_temp.ev_id('owner'));

SELECT pg_temp.ev('d1', 4701, 'owner', jsonb_build_object('collection', 'check',
    'text', 'Alice is CEO in 2024. The filings name Alice in 2024 and Bob in 2025.', 'source', 'Public filing'));
SELECT pg_temp.ev('d2', 4701, 'agent', jsonb_build_object('collection', 'check',
    'text', E'The “DAO”  enzyme—see ﬁgure 2. IL‑6 and TNF‐alpha rose. End.'));
SELECT pg_temp.ev('d-other', 4701, 'owner', jsonb_build_object('collection', 'other', 'text', 'Elsewhere.'));
SELECT pg_temp.ev('c1', 4702, 'owner', jsonb_build_object('collection', 'check', 'text', 'Alice is CEO.'));
SELECT pg_temp.ev('c2', 4702, 'agent', jsonb_build_object('collection', 'check', 'text', 'Bob is CEO.'));
SELECT pg_temp.ev('c-other', 4702, 'owner', jsonb_build_object('collection', 'other', 'text', 'Elsewhere.'));
SELECT pg_temp.ev('k1', 4704, 'agent', jsonb_build_object('collection', 'check',
    'claims', jsonb_build_array(pg_temp.k('c1'), pg_temp.k('c2')), 'reason', 'One sole CEO at a time.'));
SELECT pg_temp.ev('l1', 4703, 'owner', jsonb_build_object('collection', 'check', 'from', pg_temp.k('d1'),
    'to', pg_temp.k('c1'), 'relation', 'SUPPORTS', 'quote', 'Alice is CEO in 2024', 'reason', 'Names Alice.'));
SELECT pg_temp.ev('l2', 4703, 'agent', jsonb_build_object('collection', 'check', 'from', pg_temp.k('d1'),
    'to', pg_temp.k('k1'), 'relation', 'REBUTS', 'quote', 'Alice in 2024 and Bob in 2025', 'reason', 'Different years.'));
SELECT pg_temp.ev('l3', 4703, 'agent', jsonb_build_object('collection', 'check', 'from', pg_temp.k('d1'),
    'to', pg_temp.k('l1'), 'relation', 'REBUTS', 'quote', 'name Alice in 2024', 'reason', 'Disputes a link.'));
SELECT pg_temp.ev('l4', 4703, 'agent', jsonb_build_object('collection', 'check', 'from', pg_temp.k('d1'),
    'to', pg_temp.k('d2'), 'relation', 'SUPPORTS', 'quote', 'The filings', 'reason', 'Evidence about evidence.'));
-- Typographic variants of the same passage still cite it.
SELECT pg_temp.ev('l5', 4703, 'agent', jsonb_build_object('collection', 'check', 'from', pg_temp.k('d2'),
    'to', pg_temp.k('c2'), 'relation', 'QUALIFIES', 'quote', 'the "dao" enzyme - see figure 2. IL-6 and TNF-alpha rose. end',
    'reason', 'Curly quotes, dashes, ligature, NBSP.'));

DO $$
BEGIN
    ASSERT (SELECT array_agg(c.text ORDER BY c.text) FROM contradiction_claims m JOIN claims c ON c.id = m.claim_id
            WHERE m.contradiction_id = pg_temp.k('k1')) = ARRAY['Alice is CEO.', 'Bob is CEO.'],
        'contradiction_claims resolves the member claims';
    ASSERT (SELECT claim_ids FROM contradictions WHERE id = pg_temp.k('k1')) = ARRAY[pg_temp.k('c1'), pg_temp.k('c2')],
        'contradictions keeps the signed claim order';
    ASSERT (SELECT count(*) FROM links WHERE to_id = pg_temp.k('c1') AND from_id = pg_temp.k('d1')) = 1,
        'links exposes from/to';
    ASSERT (SELECT source FROM evidence WHERE id = pg_temp.k('d1')) = 'Public filing', 'evidence exposes source';
    ASSERT (SELECT count(*) FROM claims WHERE collection = 'check') = 2, 'claims are scoped to their collection';
    ASSERT (SELECT array_agg(id ORDER BY id) FROM evidence
            WHERE to_tsvector('simple', text) @@ plainto_tsquery('simple', 'Bob')) = ARRAY[pg_temp.k('d1')],
        'keyword search over evidence text';
END;
$$;

-- Membership: owner always; only the latest owner-signed list counts.
SELECT pg_temp.ev('m1', 4705, 'owner', jsonb_build_object('collection', 'check',
    'members', jsonb_build_array(pg_temp.ev_id('agent'), pg_temp.ev_id('old'))));
SELECT pg_temp.ev('m2', 4705, 'owner', jsonb_build_object('collection', 'check',
    'members', jsonb_build_array(pg_temp.ev_id('agent'))));
SELECT pg_temp.ev('m-forged', 4705, 'agent', jsonb_build_object('collection', 'check',
    'members', jsonb_build_array(pg_temp.ev_id('intruder'))));
DO $$
BEGIN
    ASSERT (SELECT array_agg(pubkey ORDER BY pubkey) FROM members WHERE collection = 'check') =
           (SELECT array_agg(p ORDER BY p) FROM unnest(ARRAY[pg_temp.ev_id('owner'), pg_temp.ev_id('agent')]) p),
        'members = owner + latest owner-signed list; non-owner lists are ignored';
    ASSERT (SELECT array_agg(pubkey) FROM members WHERE collection = 'other') = ARRAY[pg_temp.ev_id('owner')],
        'a new collection has only its owner';
END;
$$;

-- Profiles: latest wins, every version kept.
SELECT pg_temp.ev('p1', 0, 'agent', '{"name": "first"}');
SELECT pg_temp.ev('p2', 0, 'agent', '{"name": "second", "display_name": "extra"}');
DO $$
BEGIN
    ASSERT (SELECT name FROM profiles WHERE pubkey = pg_temp.ev_id('agent')) = 'second', 'latest profile wins';
    ASSERT (SELECT count(*) FROM events WHERE kind = 0 AND pubkey = pg_temp.ev_id('agent')) = 2, 'versions kept';
END;
$$;

-- Link quotes must appear in the grounding evidence.
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('d1'), 'to', pg_temp.k('c2'), 'relation', 'SUPPORTS', 'quote', 'Carol is CEO', 'reason', 'Invented')) $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('d1'), 'to', pg_temp.k('c2'), 'relation', 'SUPPORTS', 'quote', E'\n\t­', 'reason', 'Blank')) $sql$, '23514');
-- References: exist, right kind, same collection; QUALIFIES only to claims.
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('missing'), 'to', pg_temp.k('c2'), 'relation', 'SUPPORTS', 'quote', 'x', 'reason', 'r')) $sql$, '23503');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('d1'), 'to', pg_temp.k('missing'), 'relation', 'SUPPORTS', 'quote', 'Alice', 'reason', 'r')) $sql$, '23503');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('c1'), 'to', pg_temp.k('c2'), 'relation', 'SUPPORTS', 'quote', 'Alice', 'reason', 'from a claim')) $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('d-other'), 'to', pg_temp.k('c2'), 'relation', 'SUPPORTS', 'quote', 'Elsewhere', 'reason', 'r')) $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('d1'), 'to', pg_temp.k('c-other'), 'relation', 'SUPPORTS', 'quote', 'Alice', 'reason', 'r')) $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('d1'), 'to', pg_temp.k('m1'), 'relation', 'SUPPORTS', 'quote', 'Alice', 'reason', 'to members')) $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4703, 'agent', jsonb_build_object('collection', 'check',
    'from', pg_temp.k('d1'), 'to', pg_temp.k('k1'), 'relation', 'QUALIFIES', 'quote', 'Alice', 'reason', 'r')) $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4704, 'agent', jsonb_build_object('collection', 'check',
    'claims', jsonb_build_array(pg_temp.k('c1'), pg_temp.k('missing')), 'reason', 'r')) $sql$, '23503');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4704, 'agent', jsonb_build_object('collection', 'check',
    'claims', jsonb_build_array(pg_temp.k('c1'), pg_temp.k('d1')), 'reason', 'r')) $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4704, 'agent', jsonb_build_object('collection', 'check',
    'claims', jsonb_build_array(pg_temp.k('c1'), pg_temp.k('c-other')), 'reason', 'r')) $sql$, '23514');

-- Shapes the database can see on its own.
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4707, 'agent', '{"tool": "x", "args": {}}') $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4702, 'agent', '{"collection": "missing", "text": "x"}') $sql$, '23503');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4702, 'agent', '{"text": "no collection"}') $sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4706, 'agent', '{"collection": "check", "version": "1"}') $sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO events (id, pubkey, created_at, kind, content, sig, collection)
    VALUES (pg_temp.ev_id('bad'), pg_temp.ev_id('agent'), 0, 4702, '{"collection": "other", "text": "x"}', repeat('0', 128), 'check')
$sql$, '23514');
SELECT pg_temp.expect_error($sql$
    INSERT INTO events (id, pubkey, created_at, kind, content, sig) VALUES (pg_temp.ev_id('bad'), pg_temp.ev_id('agent'), 0, 0, '[1]', repeat('0', 128))
$sql$, '23514');
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('c1', 4702, 'owner', '{"collection": "check", "text": "Alice is CEO."}') $sql$, '23505');
SELECT pg_temp.expect_error($sql$ INSERT INTO collections (slug, owner) VALUES ('Bad Slug', pg_temp.ev_id('owner')) $sql$, '23514');

-- The ledger rejects edits and removals, even statements matching no rows.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['events', 'collections'] LOOP
        PERFORM pg_temp.expect_error(format('UPDATE %I SET created_at = created_at WHERE false', t), '55000');
        PERFORM pg_temp.expect_error(format('DELETE FROM %I WHERE false', t), '55000');
        PERFORM pg_temp.expect_error(format('TRUNCATE %I CASCADE', t), '55000');
    END LOOP;
END;
$$;

-- Full-dimensional vectors, exact cosine retrieval.
INSERT INTO embeddings (event_id, vector, model) VALUES
    (pg_temp.k('c1'), (ARRAY[1::real] || array_fill(0::real, ARRAY[4095]))::vector, 'Qwen/Qwen3-Embedding-8B'),
    (pg_temp.k('c2'), (ARRAY[0::real, 1::real] || array_fill(0::real, ARRAY[4094]))::vector, 'Qwen/Qwen3-Embedding-8B');
DO $$
BEGIN
    ASSERT (SELECT c.text FROM claims c JOIN embeddings v ON v.event_id = c.id
            ORDER BY v.vector <=> (ARRAY[1::real] || array_fill(0::real, ARRAY[4095]))::vector LIMIT 1) = 'Alice is CEO.',
        'exact cosine retrieval preserves all 4096 dimensions';
END;
$$;
SELECT pg_temp.expect_error($sql$ INSERT INTO embeddings VALUES (pg_temp.k('d1'), '[1,0]', 'x') $sql$, '22000');

ROLLBACK;
\echo 'PASS: views, membership, references, quotes, shapes, append-only, retrieval'
