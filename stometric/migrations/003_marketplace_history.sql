

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS marketplace text NOT NULL DEFAULT 'wb' CHECK (marketplace IN ('wb', 'ozon'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id bigint UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_username text;


CREATE TABLE IF NOT EXISTS card_changes (
    id          bigserial PRIMARY KEY,
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    detected_at timestamptz NOT NULL DEFAULT now(),
    wb_updated_at timestamptz,               
    kind        text NOT NULL,               
    field       text NOT NULL,               
    old_value   jsonb,
    new_value   jsonb,
    source      text NOT NULL DEFAULT 'wb'   
);
CREATE INDEX IF NOT EXISTS card_changes_acc_nm ON card_changes(account_id, nm_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS card_changes_acc_at ON card_changes(account_id, detected_at DESC);
