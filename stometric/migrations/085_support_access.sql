

SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS support_access (
    id            serial PRIMARY KEY,
    user_id       int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id  int NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    reason        text NOT NULL,                 
    granted_at    timestamptz NOT NULL DEFAULT now(),
    until         timestamptz NOT NULL,
    revoked_at    timestamptz
);
CREATE INDEX IF NOT EXISTS support_access_user ON support_access(user_id, until);
