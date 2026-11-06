


CREATE TABLE IF NOT EXISTS oz_realization_day (
    account_id  int NOT NULL REFERENCES accounts(id),
    day         date NOT NULL,
    sku         bigint NOT NULL,
    sale_qty    numeric, sale_amount numeric,       
    ret_qty     numeric, ret_amount numeric,        
    bonus       numeric,                            
    coinvest    numeric,                            
    commission  numeric,                            
    total       numeric,                            
    raw         jsonb,
    PRIMARY KEY (account_id, day, sku)
);


CREATE TABLE IF NOT EXISTS oz_buyouts (
    account_id     int NOT NULL REFERENCES accounts(id),
    posting_number text NOT NULL,
    sku            bigint NOT NULL,
    day            date,
    qty            numeric,
    amount         numeric,
    raw            jsonb,
    PRIMARY KEY (account_id, posting_number, sku)
);


CREATE TABLE IF NOT EXISTS oz_ad_sku (
    account_id   int NOT NULL REFERENCES accounts(id),
    day          date NOT NULL,
    campaign_id  bigint NOT NULL,
    sku          bigint NOT NULL,
    views numeric, clicks numeric, to_cart numeric, spent numeric,
    orders numeric, orders_money numeric, models numeric, models_money numeric,
    raw          jsonb,
    PRIMARY KEY (account_id, day, campaign_id, sku)
);
ALTER TABLE oz_ad_campaigns ADD COLUMN IF NOT EXISTS kind text;   
