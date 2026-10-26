-- Roles on a collection: owner, admin (kind 4710), member, plus account-level stewards (4711)
-- and found (4712). Apply on a database built from an older db/init.sql, on the direct
-- connection, before the matching server version starts. Fresh installs use init.sql and
-- skip this file. Safe to run once; running it again replaces the same views.
--
-- If the app connects as a role other than the one that owns these objects, grant it
-- afterwards (the block at the bottom does this for a role named tms, when that role exists):
--   GRANT SELECT ON collection_admins, collection_roster, members, stewards, collection_about TO tms;
--   GRANT EXECUTE ON FUNCTION is_collection_admin(text, text, timestamptz) TO tms;

BEGIN;

ALTER TABLE events DROP CONSTRAINT events_kind_check;
ALTER TABLE events ADD CONSTRAINT events_kind_check
    CHECK (kind IN (0, 4701, 4702, 4703, 4704, 4705, 4706, 4708, 4709, 4710, 4711, 4712));

ALTER TABLE events DROP CONSTRAINT events_collection_by_kind;
ALTER TABLE events ADD CONSTRAINT events_collection_by_kind
    CHECK ((collection IS NULL) = (kind IN (0, 4706, 4708, 4711)));

DROP VIEW IF EXISTS members;
DROP VIEW IF EXISTS collection_roster;
DROP VIEW IF EXISTS collection_admins;
DROP VIEW IF EXISTS stewards;
DROP VIEW IF EXISTS collection_about;
DROP FUNCTION IF EXISTS is_collection_admin(text, text, timestamptz);

CREATE FUNCTION is_collection_admin(col text, pk text, as_of timestamptz) RETURNS boolean
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM events e
            JOIN collections c ON c.slug = e.collection AND c.owner = e.pubkey
            WHERE e.kind = 4710 AND e.collection = col AND e.received_at <= as_of
        ) THEN EXISTS (
            SELECT 1 FROM (
                SELECT e.content FROM events e
                JOIN collections c ON c.slug = e.collection AND c.owner = e.pubkey
                WHERE e.kind = 4710 AND e.collection = col AND e.received_at <= as_of
                ORDER BY e.received_at DESC, e.id
                LIMIT 1
            ) latest
            WHERE (latest.content::jsonb -> 'admins') ? pk
              AND pk IS DISTINCT FROM (SELECT owner FROM collections WHERE slug = col)
        )
        ELSE EXISTS (
            SELECT 1 FROM events e
            JOIN collections c ON c.slug = e.collection AND c.owner = e.content::jsonb ->> 'owner'
            WHERE e.kind = 4712 AND e.collection = col AND e.pubkey = pk
              AND e.received_at <= as_of AND e.pubkey <> c.owner
        )
    END
$$;

CREATE VIEW collection_admins AS
    SELECT DISTINCT l.collection, a.pubkey
    FROM (
        SELECT DISTINCT ON (e.collection) e.collection, e.content
        FROM events e JOIN collections c ON c.slug = e.collection AND c.owner = e.pubkey
        WHERE e.kind = 4710
        ORDER BY e.collection, e.received_at DESC, e.id
    ) l
    JOIN collections c ON c.slug = l.collection
    CROSS JOIN LATERAL jsonb_array_elements_text(l.content::jsonb -> 'admins') AS a(pubkey)
    WHERE a.pubkey <> c.owner
    UNION
    SELECT e.collection, e.pubkey
    FROM events e
    JOIN collections c ON c.slug = e.collection AND c.owner = e.content::jsonb ->> 'owner'
    WHERE e.kind = 4712 AND e.pubkey <> c.owner
      AND NOT EXISTS (
          SELECT 1 FROM events a
          JOIN collections c2 ON c2.slug = a.collection AND c2.owner = a.pubkey
          WHERE a.kind = 4710 AND a.collection = e.collection);

CREATE VIEW collection_roster AS
    SELECT c.slug AS collection, c.owner AS pubkey, 'owner'::text AS role
    FROM collections c
    UNION ALL
    SELECT a.collection, a.pubkey, 'admin'
    FROM collection_admins a
    UNION ALL
    SELECT DISTINCT l.collection, m.pubkey, 'member'
    FROM (
        SELECT DISTINCT ON (e.collection) e.collection, e.content
        FROM events e JOIN collections c ON c.slug = e.collection
        WHERE e.kind = 4705
          AND (e.pubkey = c.owner OR is_collection_admin(e.collection, e.pubkey, e.received_at))
        ORDER BY e.collection, e.received_at DESC, e.id
    ) l
    JOIN collections c ON c.slug = l.collection
    CROSS JOIN LATERAL jsonb_array_elements_text(l.content::jsonb -> 'members') AS m(pubkey)
    WHERE m.pubkey <> c.owner
      AND NOT EXISTS (
          SELECT 1 FROM collection_admins a WHERE a.collection = l.collection AND a.pubkey = m.pubkey);

CREATE VIEW members AS
    SELECT collection, pubkey FROM collection_roster;

CREATE VIEW stewards AS
    SELECT l.pubkey AS grantor, s.pubkey AS steward
    FROM (
        SELECT DISTINCT ON (pubkey) pubkey, content
        FROM events WHERE kind = 4711
        ORDER BY pubkey, received_at DESC, id
    ) l
    CROSS JOIN LATERAL jsonb_array_elements_text(l.content::jsonb -> 'stewards') AS s(pubkey);

CREATE VIEW collection_about AS
    SELECT DISTINCT ON (e.collection) e.collection, e.content::jsonb ->> 'topic' AS topic,
           (e.content::jsonb ->> 'public')::boolean AS public, e.received_at
    FROM events e JOIN collections c ON c.slug = e.collection
    WHERE e.kind = 4709
      AND (e.pubkey = c.owner OR is_collection_admin(e.collection, e.pubkey, e.received_at))
    ORDER BY e.collection, e.received_at DESC, e.id;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tms') THEN
        GRANT SELECT ON collection_admins, collection_roster, members, stewards, collection_about TO tms;
        GRANT EXECUTE ON FUNCTION is_collection_admin(text, text, timestamptz) TO tms;
    END IF;
END;
$$;

COMMIT;
