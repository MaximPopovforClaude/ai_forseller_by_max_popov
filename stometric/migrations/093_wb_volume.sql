

SET lock_timeout = '10s';
ALTER TABLE wb_showcase ADD COLUMN IF NOT EXISTS volume numeric;     
ALTER TABLE wb_showcase ADD COLUMN IF NOT EXISTS weight numeric;     
CREATE TABLE IF NOT EXISTS wb_volume_hist (
    account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id      bigint NOT NULL,
    at         timestamptz NOT NULL DEFAULT now(),
    volume     numeric,
    weight     numeric
);
CREATE INDEX IF NOT EXISTS wb_volume_hist_nm ON wb_volume_hist(account_id, nm_id, at);
