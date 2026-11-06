
CREATE TABLE IF NOT EXISTS plan_cash (
    account_id int NOT NULL REFERENCES accounts(id),
    month      date NOT NULL,
    field      text NOT NULL,          
    value      numeric NOT NULL,
    updated_by int REFERENCES users(id),
    PRIMARY KEY (account_id, month, field)
);
