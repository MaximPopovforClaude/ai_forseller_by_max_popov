CREATE TABLE IF NOT EXISTS wb_ad_daily_state (
    account_id int NOT NULL REFERENCES accounts(id),
    advert_id bigint NOT NULL,
    source text NOT NULL CHECK (source IN ('campaign','budget','limits')),
    day date NOT NULL,
    data jsonb NOT NULL,
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (account_id,advert_id,source,day)
);
CREATE INDEX IF NOT EXISTS wb_ad_daily_state_period ON wb_ad_daily_state(account_id,day);

