
CREATE TABLE IF NOT EXISTS hypotheses (
    id         serial PRIMARY KEY,
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id      bigint NOT NULL,
    kind       text NOT NULL DEFAULT 'Гипотеза',      
    indicator  text,                                  
    text       text NOT NULL,
    d_from     date NOT NULL,
    days       integer,
    report     text,
    user_id    integer REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hypotheses_acc ON hypotheses(account_id, nm_id, d_from);
