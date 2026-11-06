

CREATE TABLE IF NOT EXISTS ad_outcomes (
    proposal_id bigint PRIMARY KEY REFERENCES ad_proposals(id) ON DELETE CASCADE,
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    measured_at timestamptz NOT NULL DEFAULT now(),
    before      jsonb NOT NULL,           
    after       jsonb NOT NULL,           
    delta_profit numeric,                 
    verdict     text NOT NULL,            
    days        int,                      
    final       boolean NOT NULL DEFAULT false   
);
CREATE INDEX IF NOT EXISTS ad_outcomes_acc ON ad_outcomes(account_id, measured_at DESC);

CREATE TABLE IF NOT EXISTS ad_learn (
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    action      text NOT NULL,            
    n           int NOT NULL DEFAULT 0,
    wins        int NOT NULL DEFAULT 0,
    avg_delta   numeric,
    step        numeric,                  
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, action)
);

CREATE TABLE IF NOT EXISTS ad_bid_reco (
    account_id  int NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    advert_id   bigint NOT NULL,
    nm_id       bigint NOT NULL,
    data        jsonb NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, advert_id, nm_id)
);
