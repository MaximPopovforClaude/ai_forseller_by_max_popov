
ALTER TABLE notify_settings ALTER COLUMN daily_time SET DEFAULT '10:00';
UPDATE notify_settings SET daily_time = '10:00' WHERE daily_time = '09:00';
