
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_shop_id int REFERENCES accounts(id);
