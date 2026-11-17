
CREATE TABLE IF NOT EXISTS jam_daily_progress (
    account_id bigint NOT NULL REFERENCES accounts(id),
    day date NOT NULL,
    nm_ids bigint[] NOT NULL CHECK(cardinality(nm_ids) BETWEEN 1 AND 50),
    top text NOT NULL CHECK(top IN ('openCard','orders','addToCart')),
    max_limit integer NOT NULL CHECK(max_limit IN (30,100)),
    payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(account_id,day,nm_ids,top)
);
CREATE INDEX IF NOT EXISTS jam_daily_progress_age ON jam_daily_progress(account_id,fetched_at);

