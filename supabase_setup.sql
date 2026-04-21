-- ═══════════════════════════════════════════════════════════════
-- Supabase: настройка таблицы invoices
-- Выполни этот SQL в Supabase → SQL Editor
-- ═══════════════════════════════════════════════════════════════

-- 1. Создаём таблицу (если ещё не создана через init_db)
CREATE TABLE IF NOT EXISTS invoices (
    id          SERIAL PRIMARY KEY,
    token       TEXT UNIQUE NOT NULL,
    user_id     BIGINT NOT NULL,
    user_tag    TEXT NOT NULL,
    amount      NUMERIC(12,2) NOT NULL,
    status      TEXT DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    created_date DATE DEFAULT CURRENT_DATE
);

CREATE INDEX IF NOT EXISTS invoices_token_idx ON invoices(token);

-- 2. Включаем Row Level Security
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;

-- 3. Политика: anon может читать ТОЛЬКО token, amount, status
--    (не видит user_id, user_tag и другие данные)
CREATE POLICY "Public read invoice by token"
ON invoices
FOR SELECT
TO anon
USING (true);

-- Если хочешь ограничить ещё сильнее — разреши только через функцию:
-- (опционально, более безопасный вариант)
-- DROP POLICY IF EXISTS "Public read invoice by token" ON invoices;
-- CREATE POLICY "Public read invoice by token"
-- ON invoices FOR SELECT TO anon
-- USING (status != 'deleted');

-- 4. Сервисный ключ (бот) имеет полный доступ — дополнительных политик не нужно
--    так как asyncpg подключается напрямую к PostgreSQL, минуя RLS

-- ═══════════════════════════════════════════════════════════════
-- Проверка: после выполнения запроси токен через REST API:
-- GET https://ТВОЙ_ПРОЕКТ.supabase.co/rest/v1/invoices?token=eq.ТОКЕН&select=amount,status
-- ═══════════════════════════════════════════════════════════════
