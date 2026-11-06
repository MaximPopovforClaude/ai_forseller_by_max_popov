

CREATE TABLE IF NOT EXISTS photo_blobs (
    hash       text PRIMARY KEY,                
    phash      bigint NOT NULL,                 
    path       text NOT NULL,                   
    bytes      int NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS photo_snaps (
    id        bigserial PRIMARY KEY,
    nm_id     bigint NOT NULL,
    taken_at  timestamptz NOT NULL DEFAULT now(),
    source    text NOT NULL,                    
    slots     jsonb NOT NULL,                   
    sig       text NOT NULL                     
);
CREATE INDEX IF NOT EXISTS photo_snaps_nm ON photo_snaps(nm_id, taken_at DESC);
CREATE TABLE IF NOT EXISTS photo_events (
    id        bigserial PRIMARY KEY,
    nm_id     bigint NOT NULL,
    snap_id   bigint REFERENCES photo_snaps(id),
    prev_id   bigint REFERENCES photo_snaps(id),
    day       date NOT NULL,
    summary   text NOT NULL,                    
    detail    jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS photo_events_nm ON photo_events(nm_id, day DESC);
ALTER TABLE card_comparisons ADD COLUMN IF NOT EXISTS photo_snaps jsonb;   
