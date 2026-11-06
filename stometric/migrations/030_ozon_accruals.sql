


CREATE TABLE IF NOT EXISTS oz_accrual_types (
    type_id     int PRIMARY KEY,
    name        text,
    description text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
