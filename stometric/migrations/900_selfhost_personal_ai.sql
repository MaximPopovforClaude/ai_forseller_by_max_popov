-- Public personal-installation capability. No operator, user or shop is copied.
INSERT INTO plans(key,title,about,active,sort)
VALUES ('owner','VIP (личная подписка владельца)',
        'ИИ платформы, Стометрик и GPT Image через личный Codex владельца. Только свои выбранные магазины; доступность изображений проверяется отдельно.',false,100)
ON CONFLICT(key) DO UPDATE SET title=EXCLUDED.title,about=EXCLUDED.about,active=false,price_month=NULL;
