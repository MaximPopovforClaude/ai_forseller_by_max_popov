


CREATE TABLE IF NOT EXISTS oz_products (
    account_id  int NOT NULL REFERENCES accounts(id),
    product_id  bigint NOT NULL,
    offer_id    text,
    sku         bigint,
    name        text,
    model_id    bigint,
    type_id     bigint,
    category_id bigint,
    photo       text,
    archived    boolean NOT NULL DEFAULT false,
    raw         jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, product_id)
);
CREATE INDEX IF NOT EXISTS oz_products_sku ON oz_products(account_id, sku);

CREATE TABLE IF NOT EXISTS oz_prices (
    account_id  int NOT NULL REFERENCES accounts(id),
    product_id  bigint NOT NULL,
    offer_id    text,
    price       numeric,           
    old_price   numeric,           
    marketing_price numeric,       
    min_price   numeric,
    raw         jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, product_id)
);


CREATE TABLE IF NOT EXISTS oz_stocks (
    account_id  int NOT NULL REFERENCES accounts(id),
    snap_at     timestamptz NOT NULL,
    sku         bigint NOT NULL,
    offer_id    text,
    cluster     text,
    warehouse   text,
    available   numeric,           
    other       numeric,           
    raw         jsonb
);
CREATE INDEX IF NOT EXISTS oz_stocks_snap ON oz_stocks(account_id, snap_at);


CREATE TABLE IF NOT EXISTS oz_postings (
    account_id     int NOT NULL REFERENCES accounts(id),
    posting_number text NOT NULL,
    scheme         text NOT NULL,          
    sku            bigint NOT NULL,
    offer_id       text,
    qty            int NOT NULL,
    price          numeric,                
    old_price      numeric,
    payout         numeric,                
    commission     numeric,
    status         text,
    created_at     timestamptz,
    in_process_at  timestamptz,
    order_day      date,                   
    cluster_from   text,
    cluster_to     text,
    region         text,
    raw            jsonb,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, posting_number, sku)
);
CREATE INDEX IF NOT EXISTS oz_postings_day ON oz_postings(account_id, order_day);


CREATE TABLE IF NOT EXISTS oz_transactions (
    account_id     int NOT NULL REFERENCES accounts(id),
    operation_id   bigint NOT NULL,
    operation_date timestamptz,
    op_day         date,
    operation_type text,
    type_name      text,
    tx_type        text,                   
    posting_number text,
    amount         numeric,                
    accruals_for_sale numeric,
    sale_commission   numeric,
    delivery_charge   numeric,
    return_delivery_charge numeric,
    services_total    numeric,
    skus           bigint[],
    qty            int,
    raw            jsonb,
    PRIMARY KEY (account_id, operation_id)
);
CREATE INDEX IF NOT EXISTS oz_tx_day ON oz_transactions(account_id, op_day);


CREATE TABLE IF NOT EXISTS oz_analytics (
    account_id int NOT NULL REFERENCES accounts(id),
    day        date NOT NULL,
    sku        bigint NOT NULL,
    m          jsonb NOT NULL,             
    PRIMARY KEY (account_id, day, sku)
);
