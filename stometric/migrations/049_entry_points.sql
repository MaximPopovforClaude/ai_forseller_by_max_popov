
CREATE TABLE IF NOT EXISTS entry_reports (
    id          serial PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    d_from      date NOT NULL,
    d_to        date NOT NULL,
    file_name   text,
    uploaded_by integer REFERENCES users(id),
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (account_id, d_from, d_to)
);
CREATE TABLE IF NOT EXISTS entry_rows (
    report_id   integer NOT NULL REFERENCES entry_reports(id) ON DELETE CASCADE,
    section     text NOT NULL,
    point       text NOT NULL,
    nm_id       bigint NOT NULL,
    views       numeric, clicks numeric, carts numeric, orders numeric,
    PRIMARY KEY (report_id, section, point, nm_id)
);
