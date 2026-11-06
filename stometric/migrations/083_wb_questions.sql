SET lock_timeout = '10s';



CREATE TABLE IF NOT EXISTS wb_questions (
    account_id   int NOT NULL REFERENCES accounts(id),
    id           text NOT NULL,
    nm_id        bigint,
    imt_id       bigint,
    vendor_code  text,
    product_name text,
    brand        text,
    text         text,
    created_at   timestamptz NOT NULL,
    state        text,                                  
    was_viewed   boolean,
    answer_text  text,
    answer_editable boolean,
    answered     boolean NOT NULL DEFAULT false,         
    first_seen   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, id)
);
CREATE INDEX IF NOT EXISTS wb_questions_nm ON wb_questions(account_id, nm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS wb_questions_day ON wb_questions(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS wb_questions_open ON wb_questions(account_id) WHERE NOT answered;

CREATE TABLE IF NOT EXISTS question_answers (           
    id           bigserial PRIMARY KEY,
    account_id   int NOT NULL REFERENCES accounts(id),
    question_id  text NOT NULL,
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
CREATE INDEX IF NOT EXISTS question_answers_q ON question_answers(account_id, question_id);
CREATE INDEX IF NOT EXISTS question_answers_nm ON question_answers(account_id, nm_id, created_at DESC);

CREATE TABLE IF NOT EXISTS question_rules (             
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL DEFAULT 0,
    tones       jsonb NOT NULL DEFAULT '[]',
    text        text NOT NULL DEFAULT '',
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
