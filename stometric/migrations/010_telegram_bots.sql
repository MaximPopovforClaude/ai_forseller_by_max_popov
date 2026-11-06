
CREATE TABLE IF NOT EXISTS login_tokens (            
    token_hash text PRIMARY KEY,
    user_id    int NOT NULL REFERENCES users(id),
    purpose    text NOT NULL CHECK (purpose IN ('set_password', 'login')),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz
);
CREATE TABLE IF NOT EXISTS tg_link_codes (           
    code       text PRIMARY KEY,
    user_id    int NOT NULL REFERENCES users(id),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz
);
CREATE TABLE IF NOT EXISTS reg_dialog (              
    telegram_id bigint PRIMARY KEY,
    step        text NOT NULL,
    data        jsonb NOT NULL DEFAULT '{}',
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS notify_settings (         
    user_id    int PRIMARY KEY REFERENCES users(id),
    chat_id    bigint,                               
    daily      boolean NOT NULL DEFAULT true,        
    daily_time time NOT NULL DEFAULT '09:00',        
    alerts     boolean NOT NULL DEFAULT true,        
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS notify_log (              
    id      bigserial PRIMARY KEY,
    user_id int NOT NULL REFERENCES users(id),
    kind    text NOT NULL,                           
    ref     text NOT NULL DEFAULT '',                
    sent_at timestamptz NOT NULL DEFAULT now(),
    ok      boolean NOT NULL DEFAULT true,
    UNIQUE (user_id, kind, ref)
);
