
CREATE TABLE IF NOT EXISTS jam_queries (
    account_id integer NOT NULL REFERENCES accounts(id),
    id bigint GENERATED ALWAYS AS IDENTITY,
    query text NOT NULL,
    PRIMARY KEY(account_id,id),
    UNIQUE(account_id,query)
);
CREATE TABLE IF NOT EXISTS jam_daily (
    account_id integer NOT NULL REFERENCES accounts(id),
    nm_id bigint NOT NULL,
    day date NOT NULL,
    metrics jsonb NOT NULL,
    query_count integer NOT NULL,
    max_limit smallint NOT NULL,
    conflicts integer NOT NULL DEFAULT 0,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(account_id,nm_id,day),
    CHECK (jsonb_typeof(metrics)='array')
);
CREATE INDEX IF NOT EXISTS jam_daily_shop_day ON jam_daily(account_id,day);
