
CREATE TABLE IF NOT EXISTS wb_showcase (
    account_id   int NOT NULL REFERENCES accounts(id),
    nm_id        bigint NOT NULL,
    basic        numeric,          
    price        numeric,          
    seller_price numeric,          
    spp          numeric,          
    checked_at   timestamptz NOT NULL,
    changed_at   timestamptz NOT NULL,
    PRIMARY KEY (account_id, nm_id)
);
CREATE TABLE IF NOT EXISTS wb_showcase_hist (
    account_id   int NOT NULL,
    nm_id        bigint NOT NULL,
    at           timestamptz NOT NULL DEFAULT now(),
    price        numeric,
    seller_price numeric,
    spp          numeric
);
CREATE INDEX IF NOT EXISTS wb_showcase_hist_nm ON wb_showcase_hist (account_id, nm_id, at);
