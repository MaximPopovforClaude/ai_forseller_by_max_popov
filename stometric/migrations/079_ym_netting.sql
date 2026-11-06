


SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS ym_netting (
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    tx_day      date NOT NULL,          
    order_id    bigint,
    shop_sku    text,
    model       text,                   
    kind        text NOT NULL,          
    source      text,                   
    service     text,                   
    qty         numeric,
    amount      numeric NOT NULL
);
CREATE INDEX IF NOT EXISTS ym_netting_day ON ym_netting(account_id, tx_day);
CREATE INDEX IF NOT EXISTS ym_netting_order ON ym_netting(account_id, order_id);
