CREATE TABLE IF NOT EXISTS wb_ad_observations (
    account_id int NOT NULL REFERENCES accounts(id),
    advert_id bigint NOT NULL,
    source text NOT NULL,
    data jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at timestamptz,
    PRIMARY KEY (account_id, advert_id, source)
);
