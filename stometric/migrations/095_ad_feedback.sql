

SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS ad_feedback (
    proposal_id bigint NOT NULL REFERENCES ad_proposals(id) ON DELETE CASCADE,
    user_id     int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    rating      smallint CHECK (rating IN (-1, 1)),          
    comment     text,
    snap        jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (proposal_id, user_id)
);
CREATE INDEX IF NOT EXISTS ad_feedback_acc ON ad_feedback(account_id, updated_at DESC);
