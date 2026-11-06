

CREATE TABLE IF NOT EXISTS ai_reports (
    account_id int NOT NULL REFERENCES accounts(id),
    day        date NOT NULL,
    section    text NOT NULL CHECK (section IN ('money', 'cabinet', 'competitors', 'niche')),
    title      text NOT NULL,
    body       text NOT NULL,
    source     text NOT NULL,                        
    model      text,
    data       jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, day, section)
);
