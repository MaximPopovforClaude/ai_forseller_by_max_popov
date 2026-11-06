SET lock_timeout = '10s';   

ALTER TABLE account_write_tokens ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT 'main' CHECK (purpose IN ('main','prices'));
ALTER TABLE account_write_tokens DROP CONSTRAINT IF EXISTS account_write_tokens_pkey;
ALTER TABLE account_write_tokens ADD PRIMARY KEY (account_id, purpose);
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS write_key_split boolean NOT NULL DEFAULT false;
