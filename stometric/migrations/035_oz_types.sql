
CREATE TABLE IF NOT EXISTS oz_types (
    type_id       bigint PRIMARY KEY,
    type_name     text,
    category_name text,
    updated_at    timestamptz NOT NULL DEFAULT now()
);
