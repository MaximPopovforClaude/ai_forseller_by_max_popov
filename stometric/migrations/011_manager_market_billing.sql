



CREATE TABLE IF NOT EXISTS nm_actions (              
    id         bigserial PRIMARY KEY,
    account_id int NOT NULL REFERENCES accounts(id),
    nm_id      bigint NOT NULL,
    day        date NOT NULL,
    kind       text NOT NULL,                        
    value      text,                                 
    note       text,
    user_id    int REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS nm_actions_acc_day ON nm_actions(account_id, day);
CREATE INDEX IF NOT EXISTS nm_actions_acc_nm ON nm_actions(account_id, nm_id, day);

CREATE TABLE IF NOT EXISTS nm_plans (                
    account_id int NOT NULL REFERENCES accounts(id),
    nm_id      bigint NOT NULL,
    month      date NOT NULL,                        
    qty        numeric NOT NULL,
    PRIMARY KEY (account_id, nm_id, month)
);

CREATE TABLE IF NOT EXISTS price_drafts (            
    account_id int NOT NULL REFERENCES accounts(id),
    nm_id      bigint NOT NULL,
    price      numeric NOT NULL,                     
    user_id    int REFERENCES users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);

CREATE TABLE IF NOT EXISTS shop_settings (           
    account_id int NOT NULL REFERENCES accounts(id),
    key        text NOT NULL,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, key)
);


CREATE TABLE IF NOT EXISTS competitors (
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,                     
    comp_nm_id  bigint NOT NULL,                     
    note        text,
    added_by    int REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id, comp_nm_id)
);
CREATE TABLE IF NOT EXISTS market_cache (            
    key        text PRIMARY KEY,
    data       jsonb NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS market_snap (             
    nm_id   bigint NOT NULL,
    day     date NOT NULL,
    data    jsonb NOT NULL,
    PRIMARY KEY (nm_id, day)
);
CREATE TABLE IF NOT EXISTS competitor_events (       
    id          bigserial PRIMARY KEY,
    comp_nm_id  bigint NOT NULL,
    day         date NOT NULL,
    kind        text NOT NULL,
    old_value   jsonb,
    new_value   jsonb,
    detected_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (comp_nm_id, day, kind)
);


CREATE TABLE IF NOT EXISTS insights (                
    account_id int NOT NULL REFERENCES accounts(id),
    day        date NOT NULL,
    findings   jsonb NOT NULL,
    ai_text    text,
    ai_model   text,
    built_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, day)
);


CREATE TABLE IF NOT EXISTS plans (
    key         text PRIMARY KEY,                    
    title       text NOT NULL,
    about       text,
    price_month numeric,                             
    active      boolean NOT NULL DEFAULT true,
    sort        int NOT NULL DEFAULT 0
);
INSERT INTO plans(key,title,about,sort) VALUES
  ('basic','Обычный','Все таблицы и графики по данным WB, пункт управления менеджера, журнал изменений, конкуренты.',1),
  ('ai','Наша нейросеть','Всё из «Обычного» + ИИ-разбор магазина и конкурентов каждый день: что случилось, почему и что сделать.',2),
  ('mcp','Ваша нейросеть','Всё из «Обычного» + доступ к данным кабинета по MCP для вашего Claude или другой нейросети.',3)
ON CONFLICT (key) DO NOTHING;

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan_until date;            

CREATE TABLE IF NOT EXISTS promo_codes (
    code        text PRIMARY KEY,                    
    kind        text NOT NULL CHECK (kind IN ('percent','fixed','days')),
    value       numeric NOT NULL,                    
    plan        text REFERENCES plans(key),          
    max_uses    int,                                 
    used        int NOT NULL DEFAULT 0,
    valid_until date,
    active      boolean NOT NULL DEFAULT true,
    note        text,
    created_by  int REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id           bigserial PRIMARY KEY,
    workspace_id int NOT NULL REFERENCES workspaces(id),
    user_id      int REFERENCES users(id),
    plan         text NOT NULL REFERENCES plans(key),
    months       int NOT NULL DEFAULT 1,
    days         int NOT NULL DEFAULT 0,             
    base_amount  numeric NOT NULL DEFAULT 0,
    discount     numeric NOT NULL DEFAULT 0,         
    bonus_used   numeric NOT NULL DEFAULT 0,         
    amount       numeric NOT NULL DEFAULT 0,         
    promo_code   text REFERENCES promo_codes(code),
    status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','canceled')),
    provider     text NOT NULL DEFAULT 'manual',     
    provider_id  text,
    pay_url      text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    paid_at      timestamptz
);
CREATE INDEX IF NOT EXISTS payments_ws ON payments(workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS app_settings (            
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);
INSERT INTO app_settings(key,value) VALUES
  ('ref_percent', '10'),       
  ('trial_days', '0'),         
  ('enforce_billing', 'false') 
ON CONFLICT (key) DO NOTHING;


ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_code text UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by int REFERENCES users(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_balance numeric NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS ref_rewards (
    id          bigserial PRIMARY KEY,
    referrer_id int NOT NULL REFERENCES users(id),
    referee_id  int NOT NULL REFERENCES users(id),
    payment_id  bigint REFERENCES payments(id) UNIQUE,
    amount      numeric NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
