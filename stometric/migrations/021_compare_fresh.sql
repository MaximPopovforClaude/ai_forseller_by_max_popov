
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS compare_fresh_days int NOT NULL DEFAULT 7;
