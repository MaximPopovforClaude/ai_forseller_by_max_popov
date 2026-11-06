
CREATE INDEX IF NOT EXISTS wb_feedbacks_open ON wb_feedbacks(account_id) WHERE NOT answered;
