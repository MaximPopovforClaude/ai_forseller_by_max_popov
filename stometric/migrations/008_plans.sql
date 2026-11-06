


ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan text NOT NULL DEFAULT 'basic' CHECK (plan IN ('basic', 'ai', 'mcp'));
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan_changed_at timestamptz;
