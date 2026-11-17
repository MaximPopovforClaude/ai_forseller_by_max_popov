
CREATE TABLE IF NOT EXISTS wb_ad_kw_snapshots (
    account_id int NOT NULL REFERENCES accounts(id),
    advert_id bigint NOT NULL,
    nm_id bigint NOT NULL,
    data jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (account_id, advert_id, nm_id)
);

