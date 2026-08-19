CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    balance INTEGER NOT NULL,
    CHECK (balance >= 0)
);

INSERT INTO accounts (id, name, balance)
VALUES
    (1, 'Account A', 1000),
    (2, 'Account B', 1000)
ON CONFLICT (id) DO NOTHING;
