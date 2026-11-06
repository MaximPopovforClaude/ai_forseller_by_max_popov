
CREATE TABLE IF NOT EXISTS news_events (
    id          bigserial PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind        text NOT NULL,                 
    nm_id       bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    data        jsonb NOT NULL DEFAULT '{}',
    ref         text,                          
    notified    boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS news_events_ref ON news_events(ref) WHERE ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS news_events_feed ON news_events(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS news_events_todo ON news_events(id) WHERE NOT notified;

ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS kinds jsonb NOT NULL DEFAULT '{}';
