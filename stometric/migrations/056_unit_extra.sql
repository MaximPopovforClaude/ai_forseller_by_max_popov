
CREATE TABLE IF NOT EXISTS unit_extra (
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id      bigint NOT NULL,
    marking    numeric,
    extra      numeric,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
