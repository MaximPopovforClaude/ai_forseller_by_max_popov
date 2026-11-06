

CREATE TABLE IF NOT EXISTS jam_cache (
    account_id  integer NOT NULL REFERENCES accounts(id),
    nm_id       bigint  NOT NULL,
    date_from   date    NOT NULL,
    date_to     date    NOT NULL,
    state       text    NOT NULL DEFAULT 'running',     
    items       jsonb,                                   
    error       text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    fetched_at  timestamptz,
    PRIMARY KEY (account_id, nm_id, date_from, date_to)
);

CREATE TABLE IF NOT EXISTS jam_access (
    account_id  integer PRIMARY KEY REFERENCES accounts(id),
    status      text NOT NULL,                           
    max_limit   integer,
    info        text,
    checked_at  timestamptz NOT NULL DEFAULT now()
);
