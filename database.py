import asyncpg
import os
import random
import string
from datetime import datetime, date

DB_URL = "postgresql://postgres.rmkpxtnvgnvfcymtizsg:6wx-s8x-vP8-yzc@aws-1-eu-west-3.pooler.supabase.com:5432/postgres"

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DB_URL, ssl="require")
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS approved_users (
                user_id BIGINT PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS banned_users (
                user_id   BIGINT PRIMARY KEY,
                reason    TEXT DEFAULT '',
                banned_at TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id               BIGINT PRIMARY KEY,
                username              TEXT DEFAULT '',
                full_name             TEXT DEFAULT '',
                tag                   TEXT UNIQUE,
                mentor_id             BIGINT DEFAULT NULL,
                mentor_payouts_left   INT DEFAULT 0,
                payout_count          INT DEFAULT 0,
                payout_sum            FLOAT DEFAULT 0.0,
                payout_pct            FLOAT DEFAULT 60.0,
                log_count             INT DEFAULT 0,
                onboarding_done       BOOLEAN DEFAULT FALSE,
                joined_at             TEXT
            );

            CREATE TABLE IF NOT EXISTS mentors (
                user_id       BIGINT PRIMARY KEY,
                username      TEXT DEFAULT '',
                tag           TEXT DEFAULT '',
                fee_pct       FLOAT DEFAULT 10.0,
                student_count INT DEFAULT 0,
                payout_count  INT DEFAULT 0,
                payout_sum    FLOAT DEFAULT 0.0,
                bio           TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS supports (
                user_id   BIGINT PRIMARY KEY,
                username  TEXT DEFAULT '',
                on_shift  BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS payout_history (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT,
                tag        TEXT,
                amount     FLOAT,
                created_date DATE DEFAULT CURRENT_DATE
            );

            CREATE TABLE IF NOT EXISTS user_logs (
                id             SERIAL PRIMARY KEY,
                log_number     TEXT UNIQUE,
                user_id        BIGINT,
                user_tag       TEXT,
                wallet         TEXT,
                deal_scope     TEXT,
                deal_amount    TEXT,
                wallet_balance TEXT,
                wallet_type    TEXT,
                gender         TEXT,
                language       TEXT,
                country        TEXT,
                contact        TEXT,
                messenger      TEXT,
                client_contact TEXT,
                extra_info     TEXT DEFAULT '',
                status         TEXT DEFAULT 'pending',
                support_id     BIGINT DEFAULT NULL,
                support_username TEXT DEFAULT '',
                created_at     TEXT,
                created_date   DATE DEFAULT CURRENT_DATE
            );

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
        """)
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ('work_mode', 'Дневной ворк') ON CONFLICT (key) DO NOTHING;
            INSERT INTO settings (key, value) VALUES ('project_cash', '0') ON CONFLICT (key) DO NOTHING;
            INSERT INTO settings (key, value) VALUES ('default_pct', '60') ON CONFLICT (key) DO NOTHING;
        """)
        for col_sql in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_done BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS mentor_payouts_left INT DEFAULT 0",
            "ALTER TABLE user_logs ADD COLUMN IF NOT EXISTS created_date DATE DEFAULT CURRENT_DATE",
        ]:
            try:
                await conn.execute(col_sql)
            except Exception:
                pass


def _gen_tag() -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=8))


def _gen_log_number() -> str:
    return str(random.randint(1000, 9999))


# ── Approved / Banned ─────────────────────────────────────────────────────────

async def is_approved(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM approved_users WHERE user_id=$1", user_id)
        return row is not None


async def is_banned(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM banned_users WHERE user_id=$1", user_id)
        return row is not None


async def ban_user(user_id: int, reason: str = ""):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO banned_users (user_id,reason,banned_at) VALUES ($1,$2,$3) ON CONFLICT (user_id) DO UPDATE SET reason=$2,banned_at=$3",
            user_id, reason, now,
        )
        await conn.execute("DELETE FROM approved_users WHERE user_id=$1", user_id)


async def unban_user(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM banned_users WHERE user_id=$1", user_id)
        await conn.execute("INSERT INTO approved_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_setting(key: str) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return row["value"] if row else ""


async def set_setting(key: str, value: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO settings (key,value) VALUES ($1,$2) ON CONFLICT (key) DO UPDATE SET value=$2",
            key, value,
        )


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_or_create_user(user_id: int, username: str, full_name: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        if row:
            return dict(row)
        while True:
            tag = _gen_tag()
            exists = await conn.fetchrow("SELECT user_id FROM users WHERE tag=$1", tag)
            if not exists:
                break
        default_pct = float(await get_setting("default_pct"))
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        await conn.execute(
            "INSERT INTO users (user_id,username,full_name,tag,payout_pct,joined_at) VALUES ($1,$2,$3,$4,$5,$6)",
            user_id, username, full_name, tag, default_pct, now,
        )
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row)


async def get_user(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None


async def get_user_by_tag(tag: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE tag=$1", tag)
        return dict(row) if row else None


async def get_all_users() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]


async def update_tag(user_id: int, tag: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchrow("SELECT user_id FROM users WHERE tag=$1 AND user_id!=$2", tag, user_id)
        if exists:
            return False
        await conn.execute("UPDATE users SET tag=$1 WHERE user_id=$2", tag, user_id)
        return True


async def set_user_pct(user_id: int, pct: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET payout_pct=$1 WHERE user_id=$2", pct, user_id)


async def set_all_pct(pct: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET payout_pct=$1", pct)
    await set_setting("default_pct", str(pct))


async def add_payout(user_id: int, amount: float) -> dict:
    """Начисляет выплату. Возвращает {'mentor_id': ..., 'mentor_fee': ..., 'payouts_left': ...} если есть наставник."""
    pool = await get_pool()
    result = {"mentor_id": None, "mentor_fee": 0.0, "mentor_username": ""}

    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT mentor_id, mentor_payouts_left, payout_pct FROM users WHERE user_id=$1", user_id)
        if not user:
            return result

        mentor_id = user["mentor_id"]
        payouts_left = user["mentor_payouts_left"]

        await conn.execute(
            "UPDATE users SET payout_count=payout_count+1, payout_sum=payout_sum+$1 WHERE user_id=$2",
            amount, user_id,
        )
        # Запись в историю выплат
        user_row = await conn.fetchrow("SELECT tag FROM users WHERE user_id=$1", user_id)
        tag = user_row["tag"] if user_row else ""
        await conn.execute(
            "INSERT INTO payout_history (user_id, tag, amount, created_date) VALUES ($1,$2,$3,CURRENT_DATE)",
            user_id, tag, amount,
        )

        if mentor_id and payouts_left > 0:
            mentor = await conn.fetchrow("SELECT fee_pct, username FROM mentors WHERE user_id=$1", mentor_id)
            if mentor:
                fee_pct = mentor["fee_pct"]
                mentor_fee = round(amount * fee_pct / 100, 2)
                result["mentor_id"] = mentor_id
                result["mentor_fee"] = mentor_fee
                result["mentor_username"] = mentor["username"]
                result["fee_pct"] = fee_pct

                new_left = payouts_left - 1
                await conn.execute(
                    "UPDATE users SET mentor_payouts_left=$1 WHERE user_id=$2",
                    new_left, user_id,
                )
                await conn.execute(
                    "UPDATE mentors SET payout_count=payout_count+1, payout_sum=payout_sum+$1 WHERE user_id=$2",
                    mentor_fee, mentor_id,
                )
                # Если выплаты закончились — снимаем наставника
                if new_left == 0:
                    await conn.execute("UPDATE users SET mentor_id=NULL, mentor_payouts_left=0 WHERE user_id=$1", user_id)
                    await conn.execute("UPDATE mentors SET student_count=GREATEST(0,student_count-1) WHERE user_id=$1", mentor_id)
                    result["mentor_removed"] = True

    current = float(await get_setting("project_cash"))
    await set_setting("project_cash", str(round(current + amount, 2)))
    return result


async def del_payout(user_id: int, amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT payout_sum, payout_count FROM users WHERE user_id=$1", user_id)
        if not row:
            return
        new_sum = max(0.0, round(float(row["payout_sum"]) - amount, 2))
        new_count = max(0, row["payout_count"] - 1)
        await conn.execute("UPDATE users SET payout_sum=$1, payout_count=$2 WHERE user_id=$3", new_sum, new_count, user_id)
    current = float(await get_setting("project_cash"))
    await set_setting("project_cash", str(max(0.0, round(current - amount, 2))))


async def set_onboarding_done(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET onboarding_done=TRUE WHERE user_id=$1", user_id)


async def is_onboarding_done(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT onboarding_done FROM users WHERE user_id=$1", user_id)
        return row["onboarding_done"] if row else False


# ── Mentors ───────────────────────────────────────────────────────────────────

async def add_mentor(user_id: int, username: str, tag: str, fee_pct: float = 10.0, bio: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO mentors (user_id,username,tag,fee_pct,bio) VALUES ($1,$2,$3,$4,$5) ON CONFLICT (user_id) DO UPDATE SET username=$2,tag=$3,fee_pct=$4,bio=$5",
            user_id, username, tag, fee_pct, bio,
        )


async def del_mentor_global(user_id: int):
    """Удаляет наставника полностью и снимает его со всех учеников."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET mentor_id=NULL, mentor_payouts_left=0 WHERE mentor_id=$1", user_id)
        await conn.execute("DELETE FROM mentors WHERE user_id=$1", user_id)


async def get_all_mentors() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM mentors")
        return [dict(r) for r in rows]


async def get_mentor(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM mentors WHERE user_id=$1", user_id)
        return dict(row) if row else None


async def get_mentor_by_tag(tag: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM mentors WHERE tag=$1", tag)
        return dict(row) if row else None


async def set_mentor_fee(user_id: int, fee_pct: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE mentors SET fee_pct=$1 WHERE user_id=$2", fee_pct, user_id)


async def set_mentor_bio(user_id: int, bio: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE mentors SET bio=$1 WHERE user_id=$2", bio, user_id)


async def assign_mentor(student_id: int, mentor_id: int):
    """Назначает наставника студенту на 5 выплат."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET mentor_id=$1, mentor_payouts_left=5 WHERE user_id=$2",
            mentor_id, student_id,
        )
        await conn.execute("UPDATE mentors SET student_count=student_count+1 WHERE user_id=$1", mentor_id)


async def remove_mentor_from_user(student_id: int):
    """Снимает наставника с пользователя."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT mentor_id FROM users WHERE user_id=$1", student_id)
        if user and user["mentor_id"]:
            await conn.execute("UPDATE mentors SET student_count=GREATEST(0,student_count-1) WHERE user_id=$1", user["mentor_id"])
        await conn.execute("UPDATE users SET mentor_id=NULL, mentor_payouts_left=0 WHERE user_id=$1", student_id)


# ── Supports ──────────────────────────────────────────────────────────────────

async def add_support(user_id: int, username: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO supports (user_id,username,on_shift) VALUES ($1,$2,FALSE) ON CONFLICT (user_id) DO UPDATE SET username=$2",
            user_id, username,
        )


async def del_support(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM supports WHERE user_id=$1", user_id)


async def set_support_shift(user_id: int, on_shift: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE supports SET on_shift=$1 WHERE user_id=$2", on_shift, user_id)


async def get_supports_on_shift() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username FROM supports WHERE on_shift=TRUE")
        return [dict(r) for r in rows]


async def is_support(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM supports WHERE user_id=$1", user_id)
        return row is not None


# ── Logs ──────────────────────────────────────────────────────────────────────

async def save_log(data: dict) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        while True:
            num = _gen_log_number()
            exists = await conn.fetchrow("SELECT id FROM user_logs WHERE log_number=$1", num)
            if not exists:
                break
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        today = date.today()
        await conn.execute("""
            INSERT INTO user_logs
            (log_number,user_id,user_tag,wallet,deal_scope,deal_amount,
             wallet_balance,wallet_type,gender,language,country,contact,
             messenger,client_contact,extra_info,status,created_at,created_date)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,'pending',$16,$17)
        """,
            num, data["user_id"], data["user_tag"], data["wallet"],
            data["deal_scope"], data["deal_amount"], data["wallet_balance"],
            data["wallet_type"], data["gender"], data["language"], data["country"],
            data["contact"], data["messenger"], data["client_contact"],
            data.get("extra_info", ""), now, today,
        )
    return num


async def get_log(log_number: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_logs WHERE log_number=$1", log_number)
        return dict(row) if row else None


async def take_log(log_number: str, support_id: int, support_username: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_logs SET status='taken',support_id=$1,support_username=$2 WHERE log_number=$3",
            support_id, support_username, log_number,
        )


async def set_log_result(log_number: str, result: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM user_logs WHERE log_number=$1", log_number)
        if not row:
            return
        await conn.execute("UPDATE user_logs SET status=$1 WHERE log_number=$2", result, log_number)
        if result in ("success", "fail"):
            await conn.execute("UPDATE users SET log_count=log_count+1 WHERE user_id=$1", row["user_id"])


async def get_user_logs_page(user_id: int, page: int = 0, per_page: int = 5) -> tuple:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1", user_id)
        rows = await conn.fetch(
            "SELECT log_number,wallet,created_at,status FROM user_logs WHERE user_id=$1 ORDER BY id DESC LIMIT $2 OFFSET $3",
            user_id, per_page, page * per_page,
        )
        return [dict(r) for r in rows], total


async def get_log_count(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT log_count FROM users WHERE user_id=$1", user_id)
        return row["log_count"] if row else 0


# ── Top ───────────────────────────────────────────────────────────────────────

async def get_top_all(limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tag, payout_sum, payout_count FROM users WHERE payout_sum > 0 ORDER BY payout_sum DESC LIMIT $1", limit,
        )
        return [dict(r) for r in rows]


async def get_top_today(limit: int = 10) -> list:
    pool = await get_pool()
    today = date.today()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT u.tag,
                      COALESCE(SUM(CASE WHEN l.deal_amount ~ '^[0-9]+(\.[0-9]+)?$' THEN l.deal_amount::FLOAT ELSE 0 END), 0) as total,
                      COUNT(l.id) as payout_count
               FROM users u JOIN user_logs l ON u.user_id=l.user_id
               WHERE l.created_date=$1 AND l.status IN ('success','fail')
               GROUP BY u.tag ORDER BY total DESC LIMIT $2""",
            today, limit,
        )
        return [dict(r) for r in rows]


async def get_top_month(limit: int = 10) -> list:
    pool = await get_pool()
    now = date.today()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT u.tag,
                      COALESCE(SUM(CASE WHEN l.deal_amount ~ '^[0-9]+(\.[0-9]+)?$' THEN l.deal_amount::FLOAT ELSE 0 END), 0) as total,
                      COUNT(l.id) as payout_count
               FROM users u JOIN user_logs l ON u.user_id=l.user_id
               WHERE EXTRACT(MONTH FROM l.created_date)=$1 AND EXTRACT(YEAR FROM l.created_date)=$2
                 AND l.status IN ('success','fail')
               GROUP BY u.tag ORDER BY total DESC LIMIT $3""",
            now.month, now.year, limit,
        )
        return [dict(r) for r in rows]


async def get_top_logs(limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT u.tag, COUNT(l.id) as log_count
               FROM users u
               JOIN user_logs l ON u.user_id = l.user_id
               WHERE l.status IN ('success', 'fail')
               GROUP BY u.tag
               ORDER BY log_count DESC LIMIT $1""",
            limit,
        )
        return [dict(r) for r in rows]


# ── Invoices ──────────────────────────────────────────────────────────────────

import secrets
import string as _string

def _gen_invoice_token(length: int = 8) -> str:
    """Генерирует криптографически случайный токен из букв и цифр."""
    alphabet = _string.ascii_letters + _string.digits  # a-zA-Z0-9
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def create_invoice(user_id: int, user_tag: str, amount: float) -> str:
    """Создаёт инвойс, возвращает уникальный токен."""
    pool = await get_pool()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    today = date.today()
    async with pool.acquire() as conn:
        for _ in range(10):  # до 10 попыток на случай коллизии
            token = _gen_invoice_token()
            exists = await conn.fetchrow("SELECT id FROM invoices WHERE token=$1", token)
            if not exists:
                break
        await conn.execute(
            """INSERT INTO invoices (token, user_id, user_tag, amount, status, created_at, created_date)
               VALUES ($1, $2, $3, $4, 'pending', $5, $6)""",
            token, user_id, user_tag, amount, now, today,
        )
    return token


async def get_invoice_by_token(token: str) -> dict | None:
    """Возвращает инвойс по токену."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM invoices WHERE token=$1", token)
        return dict(row) if row else None


async def get_user_invoices(user_id: int, limit: int = 10) -> list:
    """Последние инвойсы пользователя."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM invoices WHERE user_id=$1 ORDER BY id DESC LIMIT $2",
            user_id, limit,
        )
        return [dict(r) for r in rows]


async def get_all_invoices(limit: int = 50) -> list:
    """Все инвойсы (для админа)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM invoices ORDER BY id DESC LIMIT $1", limit,
        )
        return [dict(r) for r in rows]
