

SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS mrc_items (
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id       bigint NOT NULL,
    mrc         numeric NOT NULL CHECK (mrc > 0),          
    cap_pct     numeric,                                   
    mode        text NOT NULL DEFAULT 'watch' CHECK (mode IN ('off','watch','draft','auto')),
    note        text,
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
