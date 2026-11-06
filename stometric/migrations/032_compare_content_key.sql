

ALTER TABLE card_comparisons ADD COLUMN IF NOT EXISTS content_key text;
UPDATE card_comparisons SET content_key = CASE WHEN period_from IS NULL AND period_to IS NULL THEN 'sha:' || file_sha ELSE
  encode(sha256(convert_to((SELECT string_agg(x::text, ',' ORDER BY x) FROM unnest(nm_ids) x) || '|' || coalesce(period_from::text, '')
                           || '|' || coalesce(period_to::text, ''), 'UTF8')), 'hex') END
WHERE content_key IS NULL;
CREATE INDEX IF NOT EXISTS card_comparisons_ckey ON card_comparisons(content_key, id);
