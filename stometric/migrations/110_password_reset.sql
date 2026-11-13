CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash text PRIMARY KEY,
    user_id int NOT NULL REFERENCES users(id),
    issued_by int NOT NULL REFERENCES users(id),
    workspace_id int REFERENCES workspaces(id),
    delivery text NOT NULL CHECK (delivery IN ('manual','telegram')),
    status text NOT NULL CHECK (status IN ('ready','pending','failed')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);
CREATE INDEX IF NOT EXISTS password_reset_user_time ON password_reset_tokens(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS password_reset_actor_time ON password_reset_tokens(issued_by,created_at DESC);

