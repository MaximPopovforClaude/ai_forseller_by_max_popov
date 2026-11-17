
CREATE TABLE IF NOT EXISTS balance_companies (
 id bigserial PRIMARY KEY, workspace_id int NOT NULL REFERENCES workspaces(id),
 title text NOT NULL, version int NOT NULL DEFAULT 1,
 created_by int NOT NULL REFERENCES users(id), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS balance_company_shops (
 company_id bigint NOT NULL REFERENCES balance_companies(id),
 shop_id int PRIMARY KEY REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS balance_company_members ON balance_company_shops(company_id);
CREATE TABLE IF NOT EXISTS balance_batches (
 id bigserial PRIMARY KEY, company_id bigint NOT NULL REFERENCES balance_companies(id),
 shop_id int REFERENCES accounts(id), kind text NOT NULL CHECK(kind IN ('stock','assets','settlement')),
 label text NOT NULL, day date NOT NULL, payload jsonb NOT NULL,
 request_key uuid NOT NULL, digest text NOT NULL, created_by int NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(company_id,request_key)
);
CREATE INDEX IF NOT EXISTS balance_batches_latest ON balance_batches(company_id,kind,day DESC,id DESC);
CREATE TABLE IF NOT EXISTS balance_stock_runs (
 account_id int NOT NULL REFERENCES accounts(id), source text NOT NULL,
 snap_at timestamptz NOT NULL, row_count int NOT NULL CHECK(row_count>=0),
 PRIMARY KEY(account_id,source,snap_at)
);
