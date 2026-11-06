

CREATE TABLE IF NOT EXISTS shop_exclusions (
    account_id int NOT NULL REFERENCES accounts(id),
    kind       text NOT NULL CHECK (kind IN ('nm', 'brand', 'subject')),
    value      text NOT NULL,
    added_by   int REFERENCES users(id),
    added_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, kind, value)
);
