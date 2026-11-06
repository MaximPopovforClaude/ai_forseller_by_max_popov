

SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS ad_state (
    account_id  int PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    balance     jsonb,
    balance_at  timestamptz,
    summary     jsonb,
    summary_at  timestamptz
);
