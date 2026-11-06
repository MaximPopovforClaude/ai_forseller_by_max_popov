

ALTER TABLE accounts ALTER COLUMN token_env DROP NOT NULL;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS seller_oid bigint;          
CREATE TABLE IF NOT EXISTS account_tokens (
    account_id int PRIMARY KEY REFERENCES accounts(id),
    enc        bytea NOT NULL,                  
    info       jsonb NOT NULL,                  
    added_by   int REFERENCES users(id),
    added_at   timestamptz NOT NULL DEFAULT now()
);
