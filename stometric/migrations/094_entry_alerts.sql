

SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS entry_alerts (
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    day         date NOT NULL,
    nm_id       bigint NOT NULL,
    section     text NOT NULL,
    point       text NOT NULL,
    clicks      numeric, clicks_avg numeric, change_pct int,
    views       numeric, views_avg numeric, orders numeric, orders_avg numeric,
    PRIMARY KEY (account_id, day, nm_id, section, point)
);
