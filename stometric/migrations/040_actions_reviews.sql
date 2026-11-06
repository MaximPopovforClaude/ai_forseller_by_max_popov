


CREATE TABLE IF NOT EXISTS account_write_tokens (       
    account_id  int PRIMARY KEY REFERENCES accounts(id),
    enc         bytea NOT NULL,
    info        jsonb NOT NULL,                         
    agreed      text NOT NULL,                          
    added_by    int REFERENCES users(id),
    added_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS action_blocks (              
    account_id  int NOT NULL REFERENCES accounts(id),
    block       text NOT NULL,                          
    enabled     boolean NOT NULL DEFAULT false,
    settings    jsonb NOT NULL DEFAULT '{}',
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, block)
);
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS actions_paused boolean NOT NULL DEFAULT false;   

CREATE TABLE IF NOT EXISTS action_log (                 
    id          bigserial PRIMARY KEY,
    account_id  int NOT NULL REFERENCES accounts(id),
    block       text NOT NULL,
    action      text NOT NULL,
    target      text,
    before      jsonb,
    after       jsonb,
    user_id     int REFERENCES users(id),               
    by_ai       boolean NOT NULL DEFAULT false,
    ok          boolean NOT NULL,
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS action_log_acc ON action_log(account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS wb_feedbacks (               
    account_id   int NOT NULL REFERENCES accounts(id),
    id           text NOT NULL,
    nm_id        bigint,
    imt_id       bigint,
    vendor_code  text,
    product_name text,
    subject      text,
    size         text,
    valuation    int,
    text         text,
    pros         text,
    cons         text,
    bables       jsonb,
    photos       int NOT NULL DEFAULT 0,
    has_video    boolean NOT NULL DEFAULT false,
    order_status text,
    matching_size text,
    created_at   timestamptz NOT NULL,
    answer_text  text,
    answer_state text,
    answer_editable boolean,
    answered     boolean NOT NULL DEFAULT false,         
    rating_before numeric,                              
    first_seen   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, id)
);
CREATE INDEX IF NOT EXISTS wb_feedbacks_nm ON wb_feedbacks(account_id, nm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS wb_feedbacks_day ON wb_feedbacks(account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS review_answers (             
    id           bigserial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id),
    feedback_id  text NOT NULL,
    nm_id        bigint,
    text         text NOT NULL,
    source       text NOT NULL CHECK (source IN ('ai', 'manual')),
    status       text NOT NULL CHECK (status IN ('draft', 'sent', 'error', 'discarded')),
    auto         boolean NOT NULL DEFAULT false,         
    created_by   int REFERENCES users(id),
    sent_by      int REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    sent_at      timestamptz,
    error        text,
    comment      text,                                  
    comment_by   int REFERENCES users(id),
    comment_at   timestamptz
);
CREATE INDEX IF NOT EXISTS review_answers_fb ON review_answers(account_id, feedback_id);
CREATE INDEX IF NOT EXISTS review_answers_nm ON review_answers(account_id, nm_id, created_at DESC);

CREATE TABLE IF NOT EXISTS review_rules (               
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL DEFAULT 0,
    tones       jsonb NOT NULL DEFAULT '[]',
    text        text NOT NULL DEFAULT '',
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
