
CREATE TABLE IF NOT EXISTS workspace_secrets (
    workspace_id int NOT NULL REFERENCES workspaces(id),
    kind         text NOT NULL,                      
    enc          bytea NOT NULL,
    info         jsonb NOT NULL DEFAULT '{}',
    added_by     int REFERENCES users(id),
    added_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, kind)
);
