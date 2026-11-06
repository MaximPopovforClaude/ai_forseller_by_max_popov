
ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS muted_shops int[] NOT NULL DEFAULT '{}';
