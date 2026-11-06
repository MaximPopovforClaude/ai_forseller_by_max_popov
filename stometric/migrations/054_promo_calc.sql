
CREATE TABLE IF NOT EXISTS promo_uploads (
    id          serial PRIMARY KEY,
    account_id  integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name        text NOT NULL,
    items       jsonb NOT NULL,             
    file_name   text,
    uploaded_by integer REFERENCES users(id),
    uploaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS promo_calc (
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    promo      text NOT NULL,
    nm_id      bigint NOT NULL,
    PRIMARY KEY (account_id, promo, nm_id)
);

CREATE TABLE IF NOT EXISTS promo_hidden (
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    promo      text NOT NULL,
    PRIMARY KEY (account_id, promo)
);
