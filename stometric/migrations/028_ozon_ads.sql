

CREATE TABLE IF NOT EXISTS account_ad_tokens (
    account_id int PRIMARY KEY REFERENCES accounts(id),
    enc        bytea NOT NULL,
    info       jsonb NOT NULL,                  
    added_by   int REFERENCES users(id),
    added_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oz_ad_campaigns (
    account_id   int NOT NULL REFERENCES accounts(id),
    campaign_id  bigint NOT NULL,
    title        text,
    state        text,
    adv_type     text,                          
    payment_type text,                          
    daily_budget numeric,
    skus         bigint[],                      
    raw          jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, campaign_id)
);


CREATE TABLE IF NOT EXISTS oz_ad_daily (
    account_id   int NOT NULL REFERENCES accounts(id),
    day          date NOT NULL,
    campaign_id  bigint NOT NULL,
    views        numeric,
    clicks       numeric,
    spent        numeric,                       
    bonus_spent  numeric,                       
    orders       numeric,
    orders_money numeric,
    raw          jsonb,
    PRIMARY KEY (account_id, day, campaign_id)
);
