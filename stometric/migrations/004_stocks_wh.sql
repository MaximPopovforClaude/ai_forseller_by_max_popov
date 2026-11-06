
CREATE TABLE IF NOT EXISTS stocks_wh_snap (
    account_id  int NOT NULL REFERENCES accounts(id),
    snap_at     timestamptz NOT NULL,
    nm_id       bigint,
    barcode     text,
    tech_size   text,
    warehouse   text NOT NULL,
    quantity    numeric,
    data        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS stocks_wh_acc_snap ON stocks_wh_snap(account_id, snap_at);
CREATE INDEX IF NOT EXISTS stocks_wh_acc_nm ON stocks_wh_snap(account_id, nm_id, snap_at);
