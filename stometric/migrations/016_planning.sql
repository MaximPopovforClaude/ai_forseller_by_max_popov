

CREATE TABLE IF NOT EXISTS plan_items (
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    main_query  text,                                  
    query_src   text NOT NULL DEFAULT 'auto',          
    ads_share   numeric,                               
    note        text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id)
);
CREATE TABLE IF NOT EXISTS plan_cells (
    account_id  int NOT NULL REFERENCES accounts(id),
    nm_id       bigint NOT NULL,
    month       date NOT NULL,                         
    qty         numeric,  qty_src   text,              
    price       numeric,  price_src text,              
    cost        numeric,  cost_src  text,              
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, nm_id, month)
);
CREATE TABLE IF NOT EXISTS plan_season (                
    query      text NOT NULL,
    month      date NOT NULL,
    frequency  numeric,
    price      numeric,                                
    wprice     numeric,                                
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (query, month)
);
CREATE TABLE IF NOT EXISTS plan_runs (                  
    id         bigserial PRIMARY KEY,
    account_id int NOT NULL REFERENCES accounts(id),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status     text NOT NULL DEFAULT 'running',        
    progress   jsonb NOT NULL DEFAULT '{}',
    user_id    int REFERENCES users(id)
);
