

SET lock_timeout = '10s';

ALTER TABLE ai_task_runs ADD COLUMN IF NOT EXISTS request_key text;
CREATE UNIQUE INDEX IF NOT EXISTS ai_task_runs_request_key
    ON ai_task_runs(request_key) WHERE request_key IS NOT NULL;



CREATE UNIQUE INDEX IF NOT EXISTS ai_task_runs_one_open_per_shop
    ON ai_task_runs(account_id) WHERE status IN ('requested','running');

CREATE TABLE IF NOT EXISTS ai_report_runs (
    id bigserial PRIMARY KEY,
    account_id int NOT NULL REFERENCES accounts(id),
    day date NOT NULL,
    request_key text UNIQUE,
    requested_by int REFERENCES users(id),
    status text NOT NULL CHECK (status IN ('running','ok','partial','error','interrupted')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    expected_sections jsonb NOT NULL DEFAULT '[]',
    result jsonb,
    error text
);
CREATE INDEX IF NOT EXISTS ai_report_runs_acc ON ai_report_runs(account_id,id DESC);

CREATE TABLE IF NOT EXISTS ai_analytics_request_refs (
    request_key text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('tasks','reports')),
    account_id int NOT NULL REFERENCES accounts(id),
    actor_id int REFERENCES users(id),
    run_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
