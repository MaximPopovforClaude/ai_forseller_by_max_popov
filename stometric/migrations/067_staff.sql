

CREATE TABLE IF NOT EXISTS staff (
    id           serial PRIMARY KEY,
    workspace_id int NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         text NOT NULL,
    user_id      int REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS staff_name ON staff(workspace_id, lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS staff_user ON staff(workspace_id, user_id) WHERE user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS staff_articles (          
    account_id int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    nm_id      bigint NOT NULL,
    staff_id   int NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
CREATE INDEX IF NOT EXISTS staff_articles_staff ON staff_articles(staff_id, account_id);

ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS daily_mine boolean NOT NULL DEFAULT false;   
