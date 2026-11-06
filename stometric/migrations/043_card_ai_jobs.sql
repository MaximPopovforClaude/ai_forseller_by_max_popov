
CREATE TABLE IF NOT EXISTS card_ai_jobs (
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    scope       text NOT NULL,
    state       text NOT NULL CHECK (state IN ('running','done','error')),
    error       text,
    summary     text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY (account_id, nm_id)
);
