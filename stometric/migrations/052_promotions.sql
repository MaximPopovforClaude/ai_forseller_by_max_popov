
CREATE TABLE IF NOT EXISTS wb_promotions (
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    promo_id   bigint NOT NULL,
    name       text,
    kind       text,                       
    start_at   timestamptz,
    end_at     timestamptz,
    data       jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, promo_id)
);
CREATE TABLE IF NOT EXISTS wb_promo_items (
    account_id   integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    promo_id     bigint NOT NULL,
    nm_id        bigint NOT NULL,
    in_action    boolean NOT NULL,
    price        numeric,                  
    discount     numeric,
    plan_price   numeric,                  
    plan_discount numeric,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, promo_id, nm_id)
);
