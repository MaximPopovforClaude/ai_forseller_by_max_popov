
CREATE TABLE IF NOT EXISTS article_groups (
    account_id int NOT NULL REFERENCES accounts(id),
    nm_id      bigint NOT NULL,
    group_name text NOT NULL,
    PRIMARY KEY (account_id, nm_id)
);
