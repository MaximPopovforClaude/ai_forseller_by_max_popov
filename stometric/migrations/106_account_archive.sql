
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS archived_at timestamptz;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS archived_by int REFERENCES users(id);
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS archived_was_active boolean;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='accounts_archive_inactive' AND conrelid='accounts'::regclass) THEN
        ALTER TABLE accounts ADD CONSTRAINT accounts_archive_inactive CHECK (archived_at IS NULL OR NOT is_active);
    END IF;
END $$;
