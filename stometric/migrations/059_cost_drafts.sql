
CREATE TABLE IF NOT EXISTS cost_drafts (
    id          serial PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    user_id     integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        text NOT NULL,              
    items       jsonb NOT NULL,             
    valid_from  date NOT NULL,
    source      text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    applied_at  timestamptz
);
