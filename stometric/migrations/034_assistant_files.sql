
CREATE TABLE IF NOT EXISTS assistant_files (
    id          bigserial PRIMARY KEY,
    chat_id     bigint NOT NULL REFERENCES assistant_chats(id),
    user_id     int NOT NULL REFERENCES users(id),
    message_id  bigint REFERENCES assistant_messages(id),
    name        text NOT NULL,
    mime        text NOT NULL,
    path        text NOT NULL,
    size        int NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS assistant_files_msg ON assistant_files(message_id);
