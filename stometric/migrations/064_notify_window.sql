

ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS send_from time NOT NULL DEFAULT '09:30';
ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS send_to   time NOT NULL DEFAULT '23:30';

CREATE TABLE IF NOT EXISTS notify_queue (
    id         bigserial PRIMARY KEY,
    user_id    int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id    bigint NOT NULL,
    text       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notify_queue_user ON notify_queue(user_id, id);
