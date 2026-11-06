
SET lock_timeout = '10s';
ALTER TABLE ai_task_runs ADD COLUMN IF NOT EXISTS data_coverage jsonb;

