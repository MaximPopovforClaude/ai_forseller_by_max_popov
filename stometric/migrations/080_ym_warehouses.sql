
SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS ym_warehouses (
    warehouse_id bigint PRIMARY KEY,
    name         text,
    city         text,
    own          boolean NOT NULL DEFAULT false,   
    updated_at   timestamptz NOT NULL DEFAULT now()
);
