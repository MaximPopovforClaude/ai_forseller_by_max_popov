


SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS mcp_grants (
    id            serial PRIMARY KEY,
    user_id       int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id  int NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name          text NOT NULL,                  
    kind          text NOT NULL DEFAULT 'token',  
    client_id     text,                           
    token_hash    text UNIQUE,
    token_hint    text,                           
    shops         int[],                          
    level         text NOT NULL DEFAULT 'read' CHECK (level IN ('read', 'platform', 'market')),
    blocks        text[] NOT NULL DEFAULT '{}',   
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,
    revoked_at    timestamptz,
    last_used_at  timestamptz,
    calls         int NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS mcp_grants_user ON mcp_grants(user_id);

CREATE TABLE IF NOT EXISTS mcp_log (
    id        bigserial PRIMARY KEY,
    grant_id  int NOT NULL REFERENCES mcp_grants(id) ON DELETE CASCADE,
    at        timestamptz NOT NULL DEFAULT now(),
    tool      text NOT NULL,
    shop_id   int,
    method    text,
    path      text,
    ok        boolean NOT NULL,
    error     text,
    ms        int
);
CREATE INDEX IF NOT EXISTS mcp_log_grant ON mcp_log(grant_id, at DESC);


CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
    client_id     text PRIMARY KEY,
    name          text,
    redirect_uris text[] NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS mcp_oauth_codes (
    code_hash     text PRIMARY KEY,
    client_id     text NOT NULL,
    grant_id      int NOT NULL REFERENCES mcp_grants(id) ON DELETE CASCADE,
    redirect_uri  text NOT NULL,
    challenge     text NOT NULL,
    expires_at    timestamptz NOT NULL,
    used_at       timestamptz
);
