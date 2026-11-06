

CREATE TABLE IF NOT EXISTS vis_projects (             
    id           serial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id        bigint,
    title        text NOT NULL,
    description  text NOT NULL DEFAULT '',
    main_key     text,                                
    passport_id  int,                                 
    passport_model text,                              
    passport_guess jsonb,                             
    competitors  jsonb NOT NULL DEFAULT '{}',         
    answers      jsonb NOT NULL DEFAULT '{}',         
    goals        jsonb NOT NULL DEFAULT '{}',         
    note         text,                                
    created_by   int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    archived     boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS vis_projects_shop ON vis_projects(account_id, archived, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS vis_projects_nm ON vis_projects(account_id, nm_id) WHERE nm_id IS NOT NULL AND NOT archived;

CREATE TABLE IF NOT EXISTS vis_files (                
    id           serial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    project_id   int REFERENCES vis_projects(id) ON DELETE CASCADE,
    kind         text NOT NULL CHECK (kind IN ('source','passport','logo')),
    name         text NOT NULL,
    path         text NOT NULL,
    mime         text NOT NULL,
    size         int NOT NULL,
    sha          text NOT NULL,
    origin       text,                                
    meta         jsonb NOT NULL DEFAULT '{}',         
    created_by   int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS vis_files_proj ON vis_files(project_id, kind);
CREATE INDEX IF NOT EXISTS vis_files_shop ON vis_files(account_id, kind);

CREATE TABLE IF NOT EXISTS vis_brand (                
    account_id   int PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    colors       text NOT NULL DEFAULT '',
    fonts        text NOT NULL DEFAULT '',
    notes        text NOT NULL DEFAULT '',
    logo_id      int REFERENCES vis_files(id) ON DELETE SET NULL,
    updated_by   int REFERENCES users(id),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vis_briefs (               
    id           serial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    project_id   int NOT NULL REFERENCES vis_projects(id) ON DELETE CASCADE,
    nm_id        bigint,
    kind         text NOT NULL DEFAULT 'graphics' CHECK (kind IN ('graphics','rich','video')),
    version      int NOT NULL,
    data         jsonb NOT NULL,                      
    state        text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','pending','approved','returned')),
    reviewers    int[],
    review_from  int REFERENCES users(id),
    review_comment text,
    reviewed_by  int REFERENCES users(id),
    reviewed_at  timestamptz,
    created_by   int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, kind, version)
);
CREATE INDEX IF NOT EXISTS vis_briefs_shop ON vis_briefs(account_id, state);

CREATE TABLE IF NOT EXISTS vis_jobs (                 
    project_id   int NOT NULL REFERENCES vis_projects(id) ON DELETE CASCADE,
    step         text NOT NULL,
    state        text NOT NULL CHECK (state IN ('running','done','error')),
    error        text,
    summary      text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    PRIMARY KEY (project_id, step)
);
