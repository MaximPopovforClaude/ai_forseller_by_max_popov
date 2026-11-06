
CREATE TABLE IF NOT EXISTS calendar_entries (
    id bigserial PRIMARY KEY,
    workspace_id int NOT NULL REFERENCES workspaces(id),
    shop_id int REFERENCES accounts(id),
    kind text NOT NULL CHECK (kind IN ('task','note')),
    title text NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 4000),
    day date NOT NULL,
    assignee_id int REFERENCES users(id),
    created_by int NOT NULL REFERENCES users(id),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','cancelled')),
    version int NOT NULL DEFAULT 1,
    reminder_version int NOT NULL DEFAULT 1,
    request_key uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind='task' AND assignee_id IS NOT NULL) OR (kind='note' AND assignee_id IS NULL)),
    UNIQUE(workspace_id, created_by, request_key)
);
CREATE INDEX IF NOT EXISTS calendar_workspace_day ON calendar_entries(workspace_id, day, id);
CREATE INDEX IF NOT EXISTS calendar_due ON calendar_entries(assignee_id, day, id) WHERE kind='task' AND status='open';



CREATE TABLE IF NOT EXISTS calendar_reminders (
    entry_id bigint NOT NULL REFERENCES calendar_entries(id),
    reminder_version int NOT NULL,
    state text NOT NULL CHECK (state IN ('sending','sent','uncertain','deferred')),
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY(entry_id, reminder_version)
);
