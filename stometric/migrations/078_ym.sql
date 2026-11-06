


SET lock_timeout = '10s';

ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_marketplace_check;
ALTER TABLE accounts ADD CONSTRAINT accounts_marketplace_check CHECK (marketplace IN ('wb', 'ozon', 'ym'));

CREATE TABLE IF NOT EXISTS ym_campaigns (          
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    campaign_id  bigint NOT NULL,
    domain       text,
    placement    text,                              
    api_status   text,
    raw          jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, campaign_id)
);

CREATE TABLE IF NOT EXISTS ym_offers (             
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    offer_id     text NOT NULL,                     
    market_sku   bigint,                            
    name         text,
    vendor       text,
    category     text,
    photo        text,
    barcodes     text[],
    archived     boolean NOT NULL DEFAULT false,
    card_status  text,
    raw          jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, offer_id)
);
CREATE INDEX IF NOT EXISTS ym_offers_sku ON ym_offers(account_id, market_sku);

CREATE TABLE IF NOT EXISTS ym_prices (             
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    offer_id     text NOT NULL,
    price        numeric,                           
    old_price    numeric,                           
    updated      timestamptz,
    raw          jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, offer_id)
);

CREATE TABLE IF NOT EXISTS ym_stocks (             
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    snap_at      timestamptz NOT NULL,
    campaign_id  bigint NOT NULL,
    placement    text,
    warehouse_id bigint,
    offer_id     text NOT NULL,
    available    numeric,                           
    fit          numeric,                           
    other        numeric,                           
    raw          jsonb
);
CREATE INDEX IF NOT EXISTS ym_stocks_snap ON ym_stocks(account_id, snap_at);

CREATE TABLE IF NOT EXISTS ym_orders (             
    account_id    int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    order_id      bigint NOT NULL,
    campaign_id   bigint NOT NULL,
    placement     text,
    order_day     date NOT NULL,                    
    status        text,
    status_at     timestamptz,
    status_day    date,                             
    region        text,
    payment_type  text,
    fake          boolean NOT NULL DEFAULT false,
    commission    numeric,                          
    comm          jsonb,                            
    subsidy       numeric,                          
    payments      jsonb,                            
    raw           jsonb,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, order_id)
);
CREATE INDEX IF NOT EXISTS ym_orders_day ON ym_orders(account_id, order_day);
CREATE INDEX IF NOT EXISTS ym_orders_sday ON ym_orders(account_id, status_day);

CREATE TABLE IF NOT EXISTS ym_order_items (        
    account_id    int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    order_id      bigint NOT NULL,
    line          int NOT NULL,
    offer_id      text,
    market_sku    bigint,
    name          text,
    initial_qty   int,
    qty           int,
    price         numeric,                          
    buyer_total   numeric,                          
    cashback      numeric,                          
    coupons       numeric,                          
    cofinance     numeric,                          
    warehouse     text,
    PRIMARY KEY (account_id, order_id, line)
);
CREATE INDEX IF NOT EXISTS ym_order_items_sku ON ym_order_items(account_id, market_sku);
