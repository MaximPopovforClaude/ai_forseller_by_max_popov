
ALTER TABLE users ADD COLUMN IF NOT EXISTS hidden_tabs jsonb NOT NULL DEFAULT '{}'::jsonb;
