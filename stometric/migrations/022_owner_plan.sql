

ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_plan_check;
ALTER TABLE workspaces ADD CONSTRAINT workspaces_plan_check CHECK (plan IN ('basic', 'ai', 'mcp', 'owner'));
