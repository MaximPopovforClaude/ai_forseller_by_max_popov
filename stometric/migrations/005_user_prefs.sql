
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id    int NOT NULL REFERENCES users(id),
    shop_id    int NOT NULL REFERENCES accounts(id),
    key        text NOT NULL,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, shop_id, key)
);
