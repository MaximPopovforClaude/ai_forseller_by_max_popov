

SET lock_timeout = '10s';
ALTER TABLE wb_showcase ADD COLUMN IF NOT EXISTS panel_promo bigint;
CREATE TABLE IF NOT EXISTS wb_promo_days (
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id       bigint NOT NULL,
    day         date NOT NULL,
    promos      text[] NOT NULL DEFAULT '{}',     
    PRIMARY KEY (account_id, nm_id, day)
);
