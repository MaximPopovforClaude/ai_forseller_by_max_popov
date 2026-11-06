
CREATE TABLE IF NOT EXISTS card_drafts (
    id          bigserial PRIMARY KEY,
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    base        jsonb NOT NULL,                 
    changes     jsonb NOT NULL DEFAULT '{}',    
    sources     jsonb NOT NULL DEFAULT '{}',    
    ai_notes    jsonb NOT NULL DEFAULT '{}',    
    status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','applied','partial','error','discarded')),
    result      jsonb,                          
    error       text,
    rollback_of bigint REFERENCES card_drafts(id),
    created_by  int REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    applied_by  int REFERENCES users(id),
    applied_at  timestamptz
);
CREATE INDEX IF NOT EXISTS card_drafts_nm ON card_drafts(account_id, nm_id, id DESC);

CREATE TABLE IF NOT EXISTS card_media_uploads (    
    token       text PRIMARY KEY,
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    path        text NOT NULL,
    mime        text NOT NULL,
    created_by  int REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_subject_charcs (      
    subject_id  int PRIMARY KEY,
    data        jsonb NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS card_rules (             
    account_id  int PRIMARY KEY REFERENCES accounts(id),
    text        text NOT NULL DEFAULT '',
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
