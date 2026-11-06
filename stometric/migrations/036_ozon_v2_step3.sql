

CREATE TABLE IF NOT EXISTS oz_queries (
    account_id int NOT NULL REFERENCES accounts(id),
    day        date NOT NULL,
    sku        bigint NOT NULL,
    query      text NOT NULL,
    idx        int,
    position   numeric,
    searchers  numeric,
    viewers    numeric,
    conv       numeric,
    gmv        numeric,
    orders     numeric,
    PRIMARY KEY (account_id, day, sku, query)
);
CREATE TABLE IF NOT EXISTS oz_ad_phrases (
    account_id  int NOT NULL REFERENCES accounts(id),
    day         date NOT NULL,
    campaign_id bigint NOT NULL,
    sku         bigint NOT NULL,
    phrase      text NOT NULL,
    views       numeric,
    clicks      numeric,
    PRIMARY KEY (account_id, day, campaign_id, sku, phrase)
);
CREATE TABLE IF NOT EXISTS oz_checklist (
    account_id int NOT NULL REFERENCES accounts(id),
    day        date NOT NULL,
    sku        bigint NOT NULL,
    field      text NOT NULL,
    value      text,
    updated_by int REFERENCES users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, day, sku, field)
);
