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
    ASSERT (SELECT role FROM collection_roster WHERE collection = 'check' AND pubkey = pg_temp.ev_id('owner')) = 'owner',
        'the owner role is owner, even when an earlier members list names other keys';
    ASSERT NOT is_collection_admin('check', pg_temp.ev_id('agent'), clock_timestamp()),
        'a pubkey on the members list is not an admin';
END;
$$;

-- Admins: only an owner-signed list counts. An admin's members event counts from then on;
-- a later list from someone who was not an admin does not. Revoking admin does not rewrite it.
SELECT pg_temp.ev('admins1', 4710, 'owner', jsonb_build_object('collection', 'check',
    'admins', jsonb_build_array(pg_temp.ev_id('agent'))));
SELECT pg_temp.ev('m-admin', 4705, 'agent', jsonb_build_object('collection', 'check',
    'members', jsonb_build_array(pg_temp.ev_id('pal'))));
SELECT pg_temp.ev('m-stranger', 4705, 'intruder', jsonb_build_object('collection', 'check',
    'members', jsonb_build_array(pg_temp.ev_id('intruder'))));
SELECT pg_temp.ev('admins-forged', 4710, 'agent', jsonb_build_object('collection', 'check',
    'admins', jsonb_build_array(pg_temp.ev_id('intruder'))));
DO $$
BEGIN
    ASSERT (SELECT array_agg(pubkey ORDER BY pubkey) FROM collection_admins WHERE collection = 'check')
            = ARRAY[pg_temp.ev_id('agent')],
        'admins = latest owner-signed list; a non-owner list is ignored';
    ASSERT (SELECT array_agg(pubkey ORDER BY pubkey) FROM members WHERE collection = 'check') =
           (SELECT array_agg(p ORDER BY p) FROM unnest(ARRAY[pg_temp.ev_id('owner'), pg_temp.ev_id('agent'), pg_temp.ev_id('pal')]) p),
        'members = owner + admins + latest list signed by an admin at that time';
    ASSERT (SELECT role FROM collection_roster WHERE collection = 'check' AND pubkey = pg_temp.ev_id('agent')) = 'admin',
        'an admin listed again as a member is still just an admin';
END;
$$;
SELECT pg_temp.ev('admins-empty', 4710, 'owner', jsonb_build_object('collection', 'check',
    'admins', '[]'::jsonb));
DO $$
BEGIN
    ASSERT NOT EXISTS (SELECT 1 FROM collection_admins WHERE collection = 'check'),
        'an empty admins list revokes every admin';
    ASSERT (SELECT array_agg(pubkey ORDER BY pubkey) FROM members WHERE collection = 'check') =
           (SELECT array_agg(p ORDER BY p) FROM unnest(ARRAY[pg_temp.ev_id('owner'), pg_temp.ev_id('pal')]) p),
        'revoking admin drops them unless the members list still names them; the list they signed stays';
    ASSERT NOT is_collection_admin('check', pg_temp.ev_id('agent'), clock_timestamp()),
        'a revoked admin is not an admin now';
    ASSERT is_collection_admin('check', pg_temp.ev_id('agent'),
           (SELECT received_at FROM events WHERE id = pg_temp.ev_id('m-admin'))),
        'they were an admin when their members event was received';
END;
$$;

-- Stewards and found: the signer of a found event is admin until the owner signs an admins event.
-- A found event whose owner does not match the collection is ignored.
SELECT pg_temp.ev('stewards1', 4711, 'owner', jsonb_build_object(
    'stewards', jsonb_build_array(pg_temp.ev_id('agent'))));
INSERT INTO collections (slug, owner) VALUES ('founded', pg_temp.ev_id('owner')), ('mismatch', pg_temp.ev_id('owner'));
SELECT pg_temp.ev('found1', 4712, 'agent', jsonb_build_object(
    'collection', 'founded', 'owner', pg_temp.ev_id('owner')));
SELECT pg_temp.ev('found-bad', 4712, 'intruder', jsonb_build_object(
    'collection', 'mismatch', 'owner', pg_temp.ev_id('intruder')));
SELECT pg_temp.ev('about-forged', 4709, 'intruder', jsonb_build_object(
    'collection', 'founded', 'topic', 'nope', 'public', false));
SELECT pg_temp.ev('about-admin', 4709, 'agent', jsonb_build_object(
    'collection', 'founded', 'topic', 'yes', 'public', true));
DO $$
BEGIN
    ASSERT (SELECT array_agg(steward) FROM stewards WHERE grantor = pg_temp.ev_id('owner'))
            = ARRAY[pg_temp.ev_id('agent')],
        'stewards are the latest list that grantor signed';
    ASSERT (SELECT array_agg(pubkey ORDER BY pubkey) FROM members WHERE collection = 'founded') =
           (SELECT array_agg(p ORDER BY p) FROM unnest(ARRAY[pg_temp.ev_id('owner'), pg_temp.ev_id('agent')]) p),
        'the founder is an admin, and the named owner is the owner';
    ASSERT (SELECT role FROM collection_roster WHERE collection = 'founded' AND pubkey = pg_temp.ev_id('agent')) = 'admin',
        'founder role is admin';
    ASSERT (SELECT array_agg(pubkey) FROM members WHERE collection = 'mismatch') = ARRAY[pg_temp.ev_id('owner')],
        'a found event for a different owner grants nothing';
    ASSERT (SELECT topic FROM collection_about WHERE collection = 'founded') = 'yes',
        'about signed by an admin counts; one signed by a stranger does not';
END;
$$;
SELECT pg_temp.ev('admins-founded', 4710, 'owner', jsonb_build_object(
    'collection', 'founded', 'admins', '[]'::jsonb));
DO $$
BEGIN
    ASSERT NOT EXISTS (SELECT 1 FROM collection_admins WHERE collection = 'founded'),
        'the owner''s first admins event replaces the founder, even when the list is empty';
    ASSERT (SELECT pubkey FROM members WHERE collection = 'founded') = pg_temp.ev_id('owner'),
        'a replaced founder who is not on the members list loses access';
    ASSERT (SELECT topic FROM collection_about WHERE collection = 'founded') = 'yes',
        'an about event stays in force after its signer is replaced as admin';
END;
$$;
SELECT pg_temp.expect_error($sql$ SELECT pg_temp.ev('bad', 4713, 'owner', '{"collection": "check"}') $sql$, '23514');

-- Profiles: latest wins, every version kept.
-- Profiles keep their signed tags; no other kind may carry any.
INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig)
VALUES (pg_temp.ev_id('p0'), pg_temp.ev_id('agent'), 1792454399, 0, '[["client", "Damus"]]', '{"name": "zeroth"}', repeat('0', 128));
SELECT pg_temp.expect_error($sql$
    INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig, collection)
    VALUES (pg_temp.ev_id('bad'), pg_temp.ev_id('agent'), 0, 4702, '[["t", "x"]]', '{"collection": "check", "text": "x"}', repeat('0', 128), 'check')
$sql$, '23514');
SELECT pg_temp.ev('p1', 0, 'agent', '{"name": "first"}');
SELECT pg_temp.ev('p2', 0, 'agent', '{"name": "second", "display_name": "extra"}');
DO $$
BEGIN
    ASSERT (SELECT name FROM profiles WHERE pubkey = pg_temp.ev_id('agent')) = 'second', 'latest profile wins';
    ASSERT (SELECT count(*) FROM events WHERE kind = 0 AND pubkey = pg_temp.ev_id('agent')) = 3, 'versions kept';
    ASSERT (SELECT tags FROM events WHERE id = pg_temp.ev_id('p0')) = '[["client", "Damus"]]', 'profile tags kept';
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
