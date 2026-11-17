
CREATE TABLE IF NOT EXISTS photo_checks (
    nm_id bigint PRIMARY KEY,
    attempted_at timestamptz NOT NULL DEFAULT now(),
    checked_at timestamptz,
    error_code text
);


CREATE TABLE IF NOT EXISTS query_heatmap (
    account_id int NOT NULL REFERENCES accounts(id),
    nm_id bigint NOT NULL,
    data jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'empty',
    run_key text,
    requested_at timestamptz,
    updated_at timestamptz,
    PRIMARY KEY(account_id,nm_id)
);
CREATE TABLE IF NOT EXISTS query_months (
    workspace_id int NOT NULL REFERENCES workspaces(id),
    query text NOT NULL,
    month date NOT NULL,
    frequency numeric CHECK (frequency >= 0),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,query,month)
);
CREATE TABLE IF NOT EXISTS kb_card_slides (
    item_id int PRIMARY KEY REFERENCES kb_items(id) ON DELETE CASCADE,
    nm_id bigint NOT NULL,
    hashes jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'empty',
    run_key text,
    attempted_at timestamptz,
    captured_at timestamptz
);
