
SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS ym_boost (
    account_id     int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    day            date NOT NULL,
    shop_sku       text NOT NULL,
    shows_fee      numeric,   
    shows          numeric,   
    clicks_fee     numeric,   
    clicks         numeric,
    orders_fee     numeric,   
    orders         numeric,
    delivered_fee  numeric,   
    delivered      numeric,
    billed         numeric,   
    bonuses        numeric,   
    gmv_fee        numeric,   
    gmv            numeric,
    campaigns      text,
    PRIMARY KEY (account_id, day, shop_sku)
);
