
CREATE TABLE IF NOT EXISTS seo_core (                 
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id       bigint NOT NULL,
    data        jsonb NOT NULL DEFAULT '{}',
    state       text NOT NULL DEFAULT 'done' CHECK (state IN ('running','done','error')),
    error       text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    built_at    timestamptz,
    PRIMARY KEY (account_id, nm_id)
);

CREATE TABLE IF NOT EXISTS seo_kw_marks (             
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id       bigint NOT NULL,
    phrase      text NOT NULL,
    mark        text NOT NULL CHECK (mark IN ('core','main','excluded')),
    user_id     int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id, phrase)
);

CREATE TABLE IF NOT EXISTS seo_rules (                
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id       bigint NOT NULL DEFAULT 0,
    text        text NOT NULL DEFAULT '',
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);

CREATE TABLE IF NOT EXISTS seo_jobs (                 
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id       bigint NOT NULL,
    state       text NOT NULL CHECK (state IN ('running','done','error')),
    error       text,
    summary     text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY (account_id, nm_id)
);

ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS seo jsonb;                   
ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS review_state text CHECK (review_state IN ('pending','approved','returned'));
ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS review_from int REFERENCES users(id);      
ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS review_sent_at timestamptz;
ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS reviewers int[];                            
ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS review_comment text;
ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS reviewed_by int REFERENCES users(id);
ALTER TABLE card_drafts ADD COLUMN IF NOT EXISTS reviewed_at timestamptz;
CREATE INDEX IF NOT EXISTS card_drafts_review ON card_drafts(account_id, review_state) WHERE review_state = 'pending';
