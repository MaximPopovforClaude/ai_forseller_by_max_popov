


CREATE TABLE IF NOT EXISTS accounts (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,          
    title       text,                          
    token_env   text NOT NULL,                 
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS api_log (
    id          bigserial PRIMARY KEY,
    account_id  int REFERENCES accounts(id),
    method      text NOT NULL,
    params      jsonb,
    status      int,
    rows        int,
    archive     text,                          
    error       text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    duration_ms int
);
CREATE INDEX IF NOT EXISTS api_log_acc_method ON api_log(account_id, method, started_at DESC);


CREATE TABLE IF NOT EXISTS api_rate (
    account_id     int NOT NULL REFERENCES accounts(id),
    bucket         text NOT NULL,
    next_allowed   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, bucket)
);


CREATE TABLE IF NOT EXISTS collector_state (
    account_id   int NOT NULL REFERENCES accounts(id),
    collector    text NOT NULL,
    cursor       jsonb NOT NULL DEFAULT '{}',
    last_ok_at   timestamptz,
    last_error   text,
    last_run_at  timestamptz,
    PRIMARY KEY (account_id, collector)
);


CREATE TABLE IF NOT EXISTS nomenclature (
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    imt_id      bigint,
    vendor_code text,
    brand       text,
    title       text,
    subject_id  int,
    subject     text,
    created_at  timestamptz,
    updated_at  timestamptz,
    data        jsonb NOT NULL,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);

CREATE TABLE IF NOT EXISTS nm_sizes (
    account_id  int NOT NULL REFERENCES accounts(id),
    chrt_id     bigint NOT NULL,
    nm_id       bigint NOT NULL,
    tech_size   text,
    wb_size     text,
    skus        text[],
    last_seen   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, chrt_id)
);

CREATE TABLE IF NOT EXISTS orders (
    account_id       int NOT NULL REFERENCES accounts(id),
    srid             text NOT NULL,
    order_dt         timestamp NOT NULL,         
    last_change_dt   timestamp NOT NULL,
    nm_id            bigint,
    supplier_article text,
    barcode          text,
    tech_size        text,
    warehouse        text,
    warehouse_type   text,
    okrug            text,
    region           text,
    total_price      numeric,
    discount_percent numeric,
    spp              numeric,
    finished_price   numeric,
    price_with_disc  numeric,
    is_cancel        boolean,
    cancel_dt        timestamp,
    data             jsonb NOT NULL,
    first_seen       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, srid)
);
CREATE INDEX IF NOT EXISTS orders_acc_dt ON orders(account_id, order_dt);
CREATE INDEX IF NOT EXISTS orders_acc_nm_dt ON orders(account_id, nm_id, order_dt);

CREATE TABLE IF NOT EXISTS sales (
    account_id       int NOT NULL REFERENCES accounts(id),
    sale_id          text NOT NULL,              
    srid             text,
    sale_dt          timestamp NOT NULL,
    last_change_dt   timestamp NOT NULL,
    nm_id            bigint,
    supplier_article text,
    barcode          text,
    tech_size        text,
    warehouse        text,
    warehouse_type   text,
    total_price      numeric,
    discount_percent numeric,
    spp              numeric,
    for_pay          numeric,
    finished_price   numeric,
    price_with_disc  numeric,
    payment_sale_amount numeric,
    data             jsonb NOT NULL,
    first_seen       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, sale_id)
);
CREATE INDEX IF NOT EXISTS sales_acc_dt ON sales(account_id, sale_dt);
CREATE INDEX IF NOT EXISTS sales_acc_nm_dt ON sales(account_id, nm_id, sale_dt);


CREATE TABLE IF NOT EXISTS stocks_wb_snap (
    account_id  int NOT NULL REFERENCES accounts(id),
    snap_at     timestamptz NOT NULL,
    nm_id       bigint NOT NULL,
    chrt_id     bigint,
    warehouse   text NOT NULL,
    quantity    numeric,
    in_way_to_client   numeric,
    in_way_from_client numeric,
    data        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS stocks_wb_acc_snap ON stocks_wb_snap(account_id, snap_at);
CREATE INDEX IF NOT EXISTS stocks_wb_acc_nm ON stocks_wb_snap(account_id, nm_id, snap_at);

CREATE TABLE IF NOT EXISTS stocks_seller_snap (
    account_id  int NOT NULL REFERENCES accounts(id),
    snap_at     timestamptz NOT NULL,
    nm_id       bigint NOT NULL,
    chrt_id     bigint,
    warehouse   text NOT NULL,
    quantity    numeric,
    data        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS stocks_seller_acc_snap ON stocks_seller_snap(account_id, snap_at);

CREATE TABLE IF NOT EXISTS prices_snap (
    account_id  int NOT NULL REFERENCES accounts(id),
    snap_at     timestamptz NOT NULL,
    nm_id       bigint NOT NULL,
    size_id     bigint NOT NULL,
    price       numeric,
    discount    numeric,
    discounted_price numeric,
    club_discounted_price numeric,
    data        jsonb NOT NULL,
    PRIMARY KEY (account_id, snap_at, nm_id, size_id)
);



CREATE TABLE IF NOT EXISTS raw_rows (
    account_id  int NOT NULL REFERENCES accounts(id),
    source      text NOT NULL,                 
    row_key     text NOT NULL,
    row_date    date,
    data        jsonb NOT NULL,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, source, row_key)
);
CREATE INDEX IF NOT EXISTS raw_rows_src_date ON raw_rows(account_id, source, row_date);


CREATE TABLE IF NOT EXISTS cost_price (
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    valid_from  date NOT NULL,
    cost        numeric NOT NULL,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id, valid_from)
);

CREATE TABLE IF NOT EXISTS tax_settings (
    account_id  int NOT NULL REFERENCES accounts(id),
    valid_from  date NOT NULL,
    regime      text NOT NULL,                 
    rate        numeric NOT NULL DEFAULT 0,
    vat_rate    numeric NOT NULL DEFAULT 0,
    vat_deduct_wb numeric NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, valid_from)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    name       text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
