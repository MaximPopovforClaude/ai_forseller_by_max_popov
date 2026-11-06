
CREATE TABLE IF NOT EXISTS insights_staff (
    account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    day        date NOT NULL,
    staff_id   int NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    findings   jsonb NOT NULL,
    ai_text    text,
    ai_model   text,
    built_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, day, staff_id)
);
