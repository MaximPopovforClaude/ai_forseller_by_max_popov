
SET lock_timeout = '10s';
ALTER TABLE tax_settings ADD COLUMN IF NOT EXISTS cost_vat boolean NOT NULL DEFAULT false;
