
CREATE TABLE IF NOT EXISTS wb_ad_kw_daily (
    account_id int NOT NULL REFERENCES accounts(id),
    advert_id  bigint NOT NULL,
    nm_id      bigint NOT NULL,
    query      text NOT NULL,                 
    day        date NOT NULL,
    views      int,                           
    clicks     int NOT NULL DEFAULT 0,
    atbs       int NOT NULL DEFAULT 0,        
    orders     int NOT NULL DEFAULT 0,
    shks       int NOT NULL DEFAULT 0,        
    spend      numeric(14,2) NOT NULL DEFAULT 0,
    avg_pos    numeric(8,2),
    cpc        numeric(10,2),
    PRIMARY KEY (account_id, advert_id, nm_id, query, day)
);
CREATE INDEX IF NOT EXISTS wb_ad_kw_daily_day ON wb_ad_kw_daily (account_id, day);

CREATE TABLE IF NOT EXISTS wb_ad_kw_lists (
    account_id int NOT NULL REFERENCES accounts(id),
    advert_id  bigint NOT NULL,
    nm_id      bigint NOT NULL,
    query      text NOT NULL,
    state      text NOT NULL CHECK (state IN ('active', 'excluded', 'archived', 'minus')),
    bid        numeric(10,2),                 
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, advert_id, nm_id, query, state)
);
