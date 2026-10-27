-- Accounts (ACCOUNTS.md step 3): kinds 4713 account and 4714 collection agents, the accounts and
-- collection_agents views, and owner checks that accept the owner's Ledger. Apply by hand as
-- doadmin on the tms database, before deploying the code that publishes these kinds:
--   psql "$DOADMIN_URI_FOR_tms" -v ON_ERROR_STOP=1 -f db/migrate_accounts.sql
-- Needs db/migrate_signups.sql first. Safe to run once; the view bodies match db/init.sql.

BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE events DROP CONSTRAINT events_kind_check;
ALTER TABLE events ADD CONSTRAINT events_kind_check
    CHECK (kind IN (0, 4701, 4702, 4703, 4704, 4705, 4706, 4708, 4709, 4710, 4711, 4712, 4713, 4714));
ALTER TABLE events DROP CONSTRAINT events_collection_by_kind;
ALTER TABLE events ADD CONSTRAINT events_collection_by_kind
    CHECK ((collection IS NULL) = (kind IN (0, 4706, 4708, 4711, 4713)));

DROP VIEW IF EXISTS members;
DROP VIEW IF EXISTS collection_agents;
DROP VIEW IF EXISTS accounts;
DROP VIEW IF EXISTS collection_roster;
DROP VIEW IF EXISTS collection_admins;
DROP VIEW IF EXISTS stewards;
DROP VIEW IF EXISTS collection_about;
DROP FUNCTION IF EXISTS is_collection_admin(text, text, timestamptz);
DROP FUNCTION IF EXISTS acts_for(text, timestamptz);
DROP FUNCTION IF EXISTS ledger_human(text, timestamptz);

-- The human whose Ledger pk was at as_of, or NULL (ACCOUNTS.md). Only a human changes its
-- Ledger, so the human's own account events (those whose ledger is not the signer) decide it:
-- find the events that named pk as the Ledger, and keep one the human had not replaced by as_of.
-- Both lookups use indexes (events_account_ledger_idx, events_account_idx), so the cost does not
-- grow with the ledger or the number of accounts.
CREATE FUNCTION ledger_human(pk text, as_of timestamptz) RETURNS text
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT n.pubkey FROM events n
    WHERE n.kind = 4713 AND n.content::jsonb ->> 'ledger' = pk AND n.pubkey <> pk AND n.received_at <= as_of
      AND NOT EXISTS (
          SELECT 1 FROM events later
          WHERE later.kind = 4713 AND later.pubkey = n.pubkey AND later.received_at <= as_of
            AND (later.content::jsonb ->> 'ledger') IS DISTINCT FROM later.pubkey
            AND (later.received_at > n.received_at OR (later.received_at = n.received_at AND later.id < n.id)))
    LIMIT 1
$$;

-- Who pk signs for at as_of: its human when pk was a Ledger then, else pk itself.
CREATE FUNCTION acts_for(pk text, as_of timestamptz) RETURNS text
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT coalesce(ledger_human(pk, as_of), pk)
$$;

-- True when pk was an admin of col at as_of: the latest owner-signed admins event at or
-- before that time lists them, or, if the owner had not signed one yet, they signed the
-- found event that opened the collection. The owner is never an admin; that role is separate.
CREATE FUNCTION is_collection_admin(col text, pk text, as_of timestamptz) RETURNS boolean
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM events e
            JOIN collections c ON c.slug = e.collection AND c.owner = acts_for(e.pubkey, e.received_at)
            WHERE e.kind = 4710 AND e.collection = col AND e.received_at <= as_of
        ) THEN EXISTS (
            SELECT 1 FROM (
                SELECT e.content FROM events e
                JOIN collections c ON c.slug = e.collection AND c.owner = acts_for(e.pubkey, e.received_at)
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

-- Current admins. An owner-signed admins event replaces the founder; until one exists, the
-- steward who opened the collection is the admin. The owner is not in this set.
CREATE VIEW collection_admins AS
    SELECT DISTINCT l.collection, a.pubkey
    FROM (
        SELECT DISTINCT ON (e.collection) e.collection, e.content
        FROM events e JOIN collections c ON c.slug = e.collection AND c.owner = acts_for(e.pubkey, e.received_at)
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
          JOIN collections c2 ON c2.slug = a.collection AND c2.owner = acts_for(a.pubkey, a.received_at)
          WHERE a.kind = 4710 AND a.collection = e.collection);

-- One row per (collection, pubkey). Role is derived: owner, else admin, else member.
-- A pubkey cannot hold two roles. Admins are members whether or not the members list names them.
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
          AND (acts_for(e.pubkey, e.received_at) = c.owner
           OR is_collection_admin(e.collection, acts_for(e.pubkey, e.received_at), e.received_at))
        ORDER BY e.collection, e.received_at DESC, e.id
    ) l
    JOIN collections c ON c.slug = l.collection
    CROSS JOIN LATERAL jsonb_array_elements_text(l.content::jsonb -> 'members') AS m(pubkey)
    WHERE m.pubkey <> c.owner
      AND NOT EXISTS (
          SELECT 1 FROM collection_admins a WHERE a.collection = l.collection AND a.pubkey = m.pubkey);

-- Accounts (ACCOUNTS.md): the latest account event for each human, signed by the human or by
-- its Ledger at that moment. ledger is NULL when the account has none.
-- ponytail: re-sorts every account event per read (about 10 ms at 3,000 accounts); a derived
-- table kept up to date on publish if that ever shows up.
CREATE VIEW accounts AS
    SELECT DISTINCT ON (a.human) a.human, a.content::jsonb ->> 'ledger' AS ledger,
           ARRAY(SELECT jsonb_array_elements_text(a.content::jsonb -> 'agents')) AS agents, a.received_at
    FROM (SELECT CASE WHEN e.content::jsonb ->> 'ledger' = e.pubkey  -- signed by a Ledger
                      THEN ledger_human(e.pubkey, e.received_at) ELSE e.pubkey END AS human,
                 e.content, e.received_at, e.id
          FROM events e WHERE e.kind = 4713) a
    WHERE a.human IS NOT NULL
    ORDER BY a.human, a.received_at DESC, a.id;

-- The agents each person lets work in a collection: their latest collection agents event (signed
-- by them or their Ledger), keeping only keys still in their account, while they are on the roster.
CREATE VIEW collection_agents AS
    SELECT l.collection, l.person, x.agent
    FROM (
        SELECT DISTINCT ON (e.collection, acts_for(e.pubkey, e.received_at))
               e.collection, acts_for(e.pubkey, e.received_at) AS person, e.content
        FROM events e WHERE e.kind = 4714
        ORDER BY e.collection, acts_for(e.pubkey, e.received_at), e.received_at DESC, e.id
    ) l
    CROSS JOIN LATERAL jsonb_array_elements_text(l.content::jsonb -> 'agents') AS x(agent)
    JOIN accounts a ON a.human = l.person AND x.agent = ANY(a.agents)
    WHERE EXISTS (SELECT 1 FROM collection_roster r WHERE r.collection = l.collection AND r.pubkey = l.person);

-- Current membership: everyone on the roster, the agents their people chose, and the Ledger of
-- each person on the roster.
CREATE VIEW members AS
    SELECT collection, pubkey FROM collection_roster
    UNION
    SELECT collection, agent FROM collection_agents
    UNION
    SELECT r.collection, a.ledger FROM collection_roster r JOIN accounts a ON a.human = r.pubkey
    WHERE a.ledger IS NOT NULL;

-- Latest stewards event per grantor: pubkeys who may create collections that grantor owns.
CREATE VIEW stewards AS
    SELECT l.pubkey AS grantor, s.pubkey AS steward
    FROM (
        SELECT DISTINCT ON (pubkey) pubkey, content
        FROM events WHERE kind = 4711
        ORDER BY pubkey, received_at DESC, id
    ) l
    CROSS JOIN LATERAL jsonb_array_elements_text(l.content::jsonb -> 'stewards') AS s(pubkey);

-- A collection's topic and visibility: the latest about event signed by its owner or by
-- someone who was an admin at that moment. A later event from anyone else does not count.
CREATE VIEW collection_about AS
    SELECT DISTINCT ON (e.collection) e.collection, e.content::jsonb ->> 'topic' AS topic,
           (e.content::jsonb ->> 'public')::boolean AS public, e.received_at
    FROM events e JOIN collections c ON c.slug = e.collection
    WHERE e.kind = 4709
      AND (acts_for(e.pubkey, e.received_at) = c.owner
           OR is_collection_admin(e.collection, acts_for(e.pubkey, e.received_at), e.received_at))
    ORDER BY e.collection, e.received_at DESC, e.id;

CREATE INDEX IF NOT EXISTS events_account_idx ON events (pubkey, received_at) WHERE kind = 4713;
CREATE INDEX IF NOT EXISTS events_account_ledger_idx ON events ((content::jsonb ->> 'ledger')) WHERE kind = 4713;

GRANT SELECT ON collection_admins, collection_roster, accounts, collection_agents, members, stewards, collection_about TO tms;
GRANT EXECUTE ON FUNCTION is_collection_admin(text, text, timestamptz), acts_for(text, timestamptz),
    ledger_human(text, timestamptz) TO tms;

COMMIT;
