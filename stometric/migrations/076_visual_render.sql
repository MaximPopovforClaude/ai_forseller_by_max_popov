

ALTER TABLE vis_files DROP CONSTRAINT IF EXISTS vis_files_kind_check;
ALTER TABLE vis_files ADD CONSTRAINT vis_files_kind_check CHECK (kind IN ('source','passport','logo','render'));

CREATE TABLE IF NOT EXISTS vis_renders (              
    id           serial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    project_id   int REFERENCES vis_projects(id) ON DELETE CASCADE,
    brief_id     int REFERENCES vis_briefs(id) ON DELETE SET NULL,
    batch        text NOT NULL,                      
    slot         text NOT NULL,                      
    title        text NOT NULL DEFAULT '',
    model        text NOT NULL,                      
    prompt       text NOT NULL,
    refs         int[] NOT NULL DEFAULT '{}',        
    parent_id    int REFERENCES vis_renders(id) ON DELETE SET NULL,
    task         text,                               
    state        text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','done','error','canceled')),
    request_id   text,
    idem         text NOT NULL,
    error        text,
    usd          numeric(10,4),
    file_id      int REFERENCES vis_files(id) ON DELETE SET NULL,
    check_res    jsonb,                              
    created_by   int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);
CREATE INDEX IF NOT EXISTS vis_renders_proj ON vis_renders(project_id, id DESC);
CREATE INDEX IF NOT EXISTS vis_renders_open ON vis_renders(state) WHERE state IN ('queued','running');

CREATE TABLE IF NOT EXISTS vis_photos (               
    id           serial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    project_id   int REFERENCES vis_projects(id) ON DELETE CASCADE,
    file_id      int NOT NULL REFERENCES vis_files(id) ON DELETE CASCADE,
    render_id    int REFERENCES vis_renders(id) ON DELETE SET NULL,
    title        text NOT NULL DEFAULT '',
    created_by   int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS vis_photos_uniq ON vis_photos(account_id, coalesce(project_id, 0), file_id);
