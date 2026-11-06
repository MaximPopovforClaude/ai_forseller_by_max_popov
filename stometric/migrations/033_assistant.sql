

CREATE TABLE IF NOT EXISTS assistant_chats (
    id          bigserial PRIMARY KEY,
    user_id     int NOT NULL REFERENCES users(id),
    shop_id     int NOT NULL REFERENCES accounts(id),
    title       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS assistant_chats_user ON assistant_chats(user_id, shop_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS assistant_messages (
    id          bigserial PRIMARY KEY,
    chat_id     bigint NOT NULL REFERENCES assistant_chats(id),
    role        text NOT NULL,                  
    content     text,
    status      text NOT NULL DEFAULT 'done',   
    data        jsonb,                          
    model       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS assistant_messages_chat ON assistant_messages(chat_id, id);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS assistant_limit int;
INSERT INTO app_settings(key,value) VALUES ('assistant_daily_limit', '50') ON CONFLICT (key) DO NOTHING;
