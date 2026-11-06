
CREATE TABLE IF NOT EXISTS service_news (
    id          serial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    tabs        text[] NOT NULL DEFAULT '{}',     
    author_id   integer REFERENCES users(id) ON DELETE SET NULL
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS news_seen_id integer NOT NULL DEFAULT 0;
