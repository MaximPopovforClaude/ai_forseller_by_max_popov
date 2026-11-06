

CREATE TABLE IF NOT EXISTS kb_sections (
    id           serial PRIMARY KEY,
    workspace_id int NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    parent_id    int REFERENCES kb_sections(id) ON DELETE CASCADE,
    title        text NOT NULL,
    created_by   int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS kb_sections_uq ON kb_sections(workspace_id, coalesce(parent_id, 0), lower(title));

CREATE TABLE IF NOT EXISTS kb_items (
    id           serial PRIMARY KEY,
    workspace_id int NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    shop_id      int REFERENCES accounts(id) ON DELETE CASCADE,
    section_id   int REFERENCES kb_sections(id) ON DELETE SET NULL,
    kind         text NOT NULL CHECK (kind IN ('link', 'file', 'photo', 'note')),
    title        text NOT NULL,
    url          text,
    body         text,                       
    file_path    text,                       
    file_name    text,
    mime         text,
    size         int,
    text         text,                       
    description  text,
    source       text NOT NULL DEFAULT 'manual',   
    created_by   int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_by   int REFERENCES users(id),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kb_items_ws ON kb_items(workspace_id, section_id);
