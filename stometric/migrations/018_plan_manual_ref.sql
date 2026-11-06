

CREATE TABLE IF NOT EXISTS plan_manual_ref (
    account_id int NOT NULL REFERENCES accounts(id),
    nm_id      bigint NOT NULL,
    month      date NOT NULL,
    qty_ref    numeric,
    price_ref  numeric,
    source     text NOT NULL,                     
    PRIMARY KEY (account_id, nm_id, month)
);
