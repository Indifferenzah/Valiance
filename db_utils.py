import asyncio
import aiosqlite
from typing import Optional

DB_PATH = 'valiance.db'

SCHEMA_SQL = '''
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users_xp (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    text_xp INTEGER NOT NULL DEFAULT 0,
    voice_xp INTEGER NOT NULL DEFAULT 0,
    last_msg_xp_at INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER,
    is_dm INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL,
    remind_at INTEGER NOT NULL,
    recurrence TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS marriages (
    guild_id INTEGER NOT NULL,
    user_id_a INTEGER NOT NULL,
    user_id_b INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id_a, user_id_b)
);

CREATE TABLE IF NOT EXISTS reputation (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rep INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reputation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS birthdays (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    day INTEGER NOT NULL,
    month INTEGER NOT NULL,
    year INTEGER,
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(remind_at);
CREATE INDEX IF NOT EXISTS idx_rep_logs_to ON reputation_logs(to_user_id);
'''

_pool: Optional[aiosqlite.Connection] = None

async def get_db() -> aiosqlite.Connection:
    global _pool
    if _pool is None:
        _pool = await aiosqlite.connect(DB_PATH)
        await _pool.execute('PRAGMA journal_mode=WAL;')
        await _pool.execute('PRAGMA foreign_keys=ON;')
        _pool.row_factory = aiosqlite.Row
    return _pool

async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA_SQL)
    await db.commit()

# Helper to run at bot startup
async def ensure_db_ready():
    try:
        await init_db()
    except Exception:
        # try reopen
        global _pool
        if _pool is not None:
            try:
                await _pool.close()
            except Exception:
                pass
            _pool = None
        await init_db()

# Graceful shutdown
async def close_db():
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        finally:
            _pool = None
