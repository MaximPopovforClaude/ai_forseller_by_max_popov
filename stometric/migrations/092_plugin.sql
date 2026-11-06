


SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS plugin_traces (
    id         bigserial PRIMARY KEY,
    user_id    int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    grant_id   int REFERENCES mcp_grants(id) ON DELETE SET NULL,
    at         timestamptz NOT NULL DEFAULT now(),
    page       text,
    data       jsonb NOT NULL
);
