
SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS reco_map (
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id       bigint NOT NULL,
    items       jsonb NOT NULL DEFAULT '[]',   
    source      text NOT NULL DEFAULT 'ai',    
    edited_by   int REFERENCES users(id) ON DELETE SET NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
ALTER TABLE review_answers ADD COLUMN IF NOT EXISTS reco_nm bigint;
ALTER TABLE question_answers ADD COLUMN IF NOT EXISTS reco_nm bigint;
