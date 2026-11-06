
CREATE TABLE IF NOT EXISTS seo_marks (
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id      bigint NOT NULL,
    word       text NOT NULL,
    mark       text NOT NULL CHECK (mark IN ('add', 'remove')),
    user_id    integer REFERENCES users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id, word)
);
