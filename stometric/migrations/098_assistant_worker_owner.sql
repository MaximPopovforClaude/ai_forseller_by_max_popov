

SET LOCAL lock_timeout = '10s';
ALTER TABLE assistant_messages ADD COLUMN IF NOT EXISTS worker_owner jsonb;


ALTER TABLE api_rate ADD COLUMN IF NOT EXISTS blocked_until timestamptz;
