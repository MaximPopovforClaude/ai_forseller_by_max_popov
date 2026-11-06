
CREATE TABLE IF NOT EXISTS spp_state (
    account_id   integer NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id        bigint NOT NULL,
    spp          numeric,                 
    price        numeric,                 
    last_order   timestamp,               
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
