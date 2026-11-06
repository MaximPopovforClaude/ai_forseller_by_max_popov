
CREATE TABLE IF NOT EXISTS checklist_max (
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id      bigint NOT NULL,
    field      text NOT NULL,          
    value      numeric NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id, field)
);
CREATE TABLE IF NOT EXISTS ext_costs (
    id         serial PRIMARY KEY,
    account_id integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id      bigint NOT NULL,
    kind       text NOT NULL DEFAULT 'ext' CHECK (kind IN ('ext', 'giveaway')),   
    source     text,                   
    d_from     date NOT NULL,
    d_to       date,                   
    cost       numeric NOT NULL DEFAULT 0,
    qty        numeric,                
    clicks     numeric,                
    comment    text,
    user_id    integer REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ext_costs_acc ON ext_costs(account_id, nm_id, d_from);
