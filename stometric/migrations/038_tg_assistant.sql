
ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS bot text NOT NULL DEFAULT 'notify' CHECK (bot IN ('notify', 'assistant'));
ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS ai boolean NOT NULL DEFAULT true;      
ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS as_shop int REFERENCES accounts(id) ON DELETE SET NULL;   
ALTER TABLE notify_settings ADD COLUMN IF NOT EXISTS as_chat int REFERENCES assistant_chats(id) ON DELETE SET NULL;  
