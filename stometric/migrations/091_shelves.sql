


SET lock_timeout = '10s';
CREATE TABLE IF NOT EXISTS shelf_snap (
    day     date NOT NULL,
    nm_id   bigint NOT NULL,                 
    kind    smallint NOT NULL DEFAULT 1,     
    total   int,                             
    nms     bigint[] NOT NULL,               
    taken_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (day, nm_id, kind)
);
CREATE INDEX IF NOT EXISTS shelf_snap_nms ON shelf_snap USING gin (nms);
CREATE INDEX IF NOT EXISTS shelf_snap_nm ON shelf_snap (nm_id, day);


CREATE TABLE IF NOT EXISTS shelf_cards (
    nm_id       bigint PRIMARY KEY,
    name        text,
    brand       text,
    supplier    text,
    supplier_id bigint,
    subject_id  int,
    rating      numeric,
    feedbacks   int,
    price       numeric,                     
    seen_at     timestamptz NOT NULL DEFAULT now()
);
