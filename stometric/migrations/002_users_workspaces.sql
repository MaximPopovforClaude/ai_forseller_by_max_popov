


CREATE TABLE IF NOT EXISTS workspaces (            
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS workspace_id int REFERENCES workspaces(id);

CREATE TABLE IF NOT EXISTS users (
    id            serial PRIMARY KEY,
    email         text NOT NULL UNIQUE,            
    name          text,
    password_hash text,                            
    is_superadmin boolean NOT NULL DEFAULT false,  
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);



CREATE TABLE IF NOT EXISTS memberships (
    user_id      int NOT NULL REFERENCES users(id),
    workspace_id int NOT NULL REFERENCES workspaces(id),
    role         text NOT NULL CHECK (role IN ('owner','admin','editor','viewer')),
    shop_ids     int[],                            
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS invites (
    token_hash   text PRIMARY KEY,                 
    workspace_id int NOT NULL REFERENCES workspaces(id),
    email        text NOT NULL,
    role         text NOT NULL CHECK (role IN ('admin','editor','viewer')),
    shop_ids     int[],
    created_by   int REFERENCES users(id),
    expires_at   timestamptz NOT NULL,
    used_at      timestamptz
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  text PRIMARY KEY,
    user_id     int NOT NULL REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    ip          text,
    user_agent  text
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);


CREATE TABLE IF NOT EXISTS audit_log (
    id           bigserial PRIMARY KEY,
    user_id      int REFERENCES users(id),
    workspace_id int REFERENCES workspaces(id),
    action       text NOT NULL,
    details      jsonb,
    at           timestamptz NOT NULL DEFAULT now()
);





