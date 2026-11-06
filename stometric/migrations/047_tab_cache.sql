
CREATE TABLE IF NOT EXISTS tab_cache (
    account_id  integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    tab         text NOT NULL,
    fkey        text NOT NULL,
    ver         text NOT NULL,
    result      jsonb NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, tab, fkey)
);
