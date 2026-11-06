
CREATE TABLE IF NOT EXISTS card_comparisons (
    id          bigserial PRIMARY KEY,
    user_id     int NOT NULL REFERENCES users(id),
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    file_sha    text NOT NULL,
    file_name   text,
    period_from date,
    period_to   date,
    nm_ids      bigint[] NOT NULL,
    data        jsonb NOT NULL,
    photos      jsonb NOT NULL DEFAULT '{}',
    is_public   boolean NOT NULL DEFAULT false,
    ai_text     text,
    ai_model    text,
    UNIQUE (user_id, file_sha)
);
CREATE INDEX IF NOT EXISTS card_comparisons_nm ON card_comparisons USING gin (nm_ids);
CREATE TABLE IF NOT EXISTS comparison_views (
    user_id       int NOT NULL REFERENCES users(id),
    comparison_id bigint NOT NULL REFERENCES card_comparisons(id) ON DELETE CASCADE,
    viewed_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, comparison_id)
);
