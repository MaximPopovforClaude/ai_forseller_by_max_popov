
CREATE TABLE IF NOT EXISTS comparison_saved (
    user_id       int NOT NULL REFERENCES users(id),
    comparison_id bigint NOT NULL REFERENCES card_comparisons(id) ON DELETE CASCADE,
    saved_at      timestamptz NOT NULL DEFAULT now(),
    ai_text       text,
    ai_model      text,
    PRIMARY KEY (user_id, comparison_id)
);
CREATE TABLE IF NOT EXISTS compare_subs (
    user_id    int NOT NULL REFERENCES users(id),
    nm_id      bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, nm_id)
);
CREATE TABLE IF NOT EXISTS compare_notified (               
    user_id       int NOT NULL REFERENCES users(id),
    comparison_id bigint NOT NULL REFERENCES card_comparisons(id) ON DELETE CASCADE,
    sent_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, comparison_id)
);
