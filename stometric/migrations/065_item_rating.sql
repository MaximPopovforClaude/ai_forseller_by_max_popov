

CREATE TABLE IF NOT EXISTS wb_item_rating (
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id        bigint NOT NULL,
    day          date NOT NULL,
    rating       numeric,           
    percentile   numeric,           
    card_rating  numeric,           
    s5 int, s4 int, s3 int, s2 int, s1 int,          
    m5 int, m4 int, m3 int, m2 int, m1 int,          
    disqualified int,               
    pinned       boolean,           
    shadowed     boolean,           
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id, day)
);

CREATE TABLE IF NOT EXISTS wb_seller_rating (
    account_id   int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    day          date NOT NULL,
    rating       numeric,
    s5 int, s4 int, s3 int, s2 int, s1 int,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, day)
);
