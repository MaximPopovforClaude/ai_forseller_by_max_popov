
CREATE TABLE IF NOT EXISTS agg_nm_day (
    account_id int NOT NULL REFERENCES accounts(id),
    nm_id      bigint NOT NULL,
    day        date NOT NULL,
    data       jsonb NOT NULL,
    PRIMARY KEY (account_id, nm_id, day)
);
CREATE INDEX IF NOT EXISTS agg_nm_day_acc_day ON agg_nm_day(account_id, day);
CREATE TABLE IF NOT EXISTS agg_real_week (
    account_id int NOT NULL REFERENCES accounts(id),
    seq        int NOT NULL,
    date_from  date,
    data       jsonb NOT NULL,
    PRIMARY KEY (account_id, seq)
);
CREATE TABLE IF NOT EXISTS agg_state (
    account_id int NOT NULL REFERENCES accounts(id),
    name       text NOT NULL,
    covered_from date, covered_to date,
    built_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, name)
);
