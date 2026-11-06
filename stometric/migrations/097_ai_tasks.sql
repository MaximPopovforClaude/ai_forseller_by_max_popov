



SET lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS ai_task_shops (                 
    account_id  int PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_task_runs (                  
    id          bigserial PRIMARY KEY,
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    day         date NOT NULL,                             
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    entry_ok    boolean,                                   
    status      text NOT NULL DEFAULT 'running',           
    summary     text,                                      
    model       text,
    error       text,
    requested_by int REFERENCES users(id)                  
);
CREATE INDEX IF NOT EXISTS ai_task_runs_acc ON ai_task_runs(account_id, day DESC, id DESC);

CREATE TABLE IF NOT EXISTS ai_tasks (
    id          bigserial PRIMARY KEY,
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    run_id      bigint REFERENCES ai_task_runs(id) ON DELETE SET NULL,
    day         date NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    active      boolean NOT NULL DEFAULT true,             
    title       text NOT NULL,                             
    why         text NOT NULL,                             
    steps       text,                                      
    tag         text NOT NULL,                             
    certainty   text NOT NULL,                             
    effect_week numeric,                                   
    priority    int NOT NULL DEFAULT 50,
    nm_ids      bigint[] NOT NULL DEFAULT '{}',
    vc          text,                                      
    check_spec  jsonb,                                     
    status      text NOT NULL DEFAULT 'new',               
    status_by   text,                                      
    status_note text,
    status_at   timestamptz,
    status_user int REFERENCES users(id),
    done_at     timestamptz,                               
    outcome     jsonb                                      
);
CREATE INDEX IF NOT EXISTS ai_tasks_acc ON ai_tasks(account_id, day DESC, priority DESC);

CREATE TABLE IF NOT EXISTS ai_task_feedback (
    task_id     bigint NOT NULL REFERENCES ai_tasks(id) ON DELETE CASCADE,
    user_id     int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    rating      smallint CHECK (rating IN (-1, 1)),
    comment     text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, user_id)
);
CREATE INDEX IF NOT EXISTS ai_task_feedback_acc ON ai_task_feedback(account_id, updated_at DESC);



