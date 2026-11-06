
ALTER TABLE ai_reports DROP CONSTRAINT IF EXISTS ai_reports_section_check;
ALTER TABLE ai_reports ADD CONSTRAINT ai_reports_section_check CHECK (section IN ('day', 'money', 'cabinet', 'competitors', 'niche', 'search'));
