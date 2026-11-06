

CREATE TABLE IF NOT EXISTS ad_proposals (
    id          bigserial PRIMARY KEY,
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    batch_at    timestamptz NOT NULL DEFAULT now(),       
    kind        text NOT NULL,                            
    advert_id   bigint,
    nm_id       bigint,
    query       text,                                     
    params      jsonb NOT NULL,                           
    reason      text NOT NULL,                            
    effect_week numeric,                                  
    metrics     jsonb,                                    
    priority    int NOT NULL DEFAULT 0,
    source      text NOT NULL DEFAULT 'rules',            
    status      text NOT NULL DEFAULT 'new',              
    dkey        text NOT NULL,                            
    decided_by  int REFERENCES users(id),
    decided_at  timestamptz,
    error       text
);
CREATE INDEX IF NOT EXISTS ad_proposals_acc ON ad_proposals(account_id, status, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ad_proposals_new ON ad_proposals(account_id, dkey) WHERE status = 'new';

CREATE TABLE IF NOT EXISTS ad_notes (                    
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    batch_at    timestamptz NOT NULL,
    body        text NOT NULL,
    model       text,
    PRIMARY KEY (account_id, batch_at)
);
