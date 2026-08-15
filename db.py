import sqlite3
from contextlib import contextmanager

DB_PATH = "streakbot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    leaderboard_enabled INTEGER NOT NULL DEFAULT 0,
    leaderboard_hour INTEGER,
    leaderboard_minute INTEGER,
    leaderboard_timezone TEXT,
    leaderboard_last_posted_date TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    activity TEXT NOT NULL,
    start_hour INTEGER NOT NULL,
    start_minute INTEGER NOT NULL,
    end_hour INTEGER NOT NULL,
    end_minute INTEGER NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    last_start_date TEXT,
    last_nudge_date TEXT,
    last_result_date TEXT,
    UNIQUE (user_id, guild_id, label)
);

CREATE TABLE IF NOT EXISTS streaks (
    reminder_id INTEGER PRIMARY KEY REFERENCES reminders(id),
    current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0,
    last_checkin_date TEXT
);

CREATE TABLE IF NOT EXISTS pending_checkins (
    message_id INTEGER PRIMARY KEY,
    reminder_id INTEGER NOT NULL,
    date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_timezone (
    user_id INTEGER PRIMARY KEY,
    timezone TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added to guild_config after its initial release. CREATE TABLE IF NOT EXISTS only
# creates missing tables, not missing columns on ones that already exist, so an older db file
# needs these patched in by hand.
GUILD_CONFIG_MIGRATIONS = [
    ("leaderboard_enabled", "ALTER TABLE guild_config ADD COLUMN leaderboard_enabled INTEGER NOT NULL DEFAULT 0"),
    ("leaderboard_hour", "ALTER TABLE guild_config ADD COLUMN leaderboard_hour INTEGER"),
    ("leaderboard_minute", "ALTER TABLE guild_config ADD COLUMN leaderboard_minute INTEGER"),
    ("leaderboard_timezone", "ALTER TABLE guild_config ADD COLUMN leaderboard_timezone TEXT"),
    ("leaderboard_last_posted_date", "ALTER TABLE guild_config ADD COLUMN leaderboard_last_posted_date TEXT"),
]


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(guild_config)")}
        for column, ddl in GUILD_CONFIG_MIGRATIONS:
            if column not in existing_columns:
                conn.execute(ddl)


def set_guild_channel(guild_id, channel_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO guild_config (guild_id, channel_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            (guild_id, channel_id),
        )


def get_guild_channel(guild_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT channel_id FROM guild_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row["channel_id"] if row else None


def set_leaderboard_schedule(guild_id, hour, minute, timezone):
    with get_conn() as conn:
        conn.execute(
            """UPDATE guild_config SET leaderboard_enabled = 1, leaderboard_hour = ?,
               leaderboard_minute = ?, leaderboard_timezone = ?, leaderboard_last_posted_date = NULL
               WHERE guild_id = ?""",
            (hour, minute, timezone, guild_id),
        )


def disable_leaderboard(guild_id):
    with get_conn() as conn:
        conn.execute("UPDATE guild_config SET leaderboard_enabled = 0 WHERE guild_id = ?", (guild_id,))


def mark_leaderboard_posted(guild_id, date_str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE guild_config SET leaderboard_last_posted_date = ? WHERE guild_id = ?",
            (date_str, guild_id),
        )


def get_guilds_with_leaderboard_enabled():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM guild_config WHERE leaderboard_enabled = 1").fetchall()


def get_user_timezone(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT timezone FROM user_timezone WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["timezone"] if row else None


def set_user_timezone(user_id, timezone):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_timezone (user_id, timezone) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone",
            (user_id, timezone),
        )


def upsert_reminder(user_id, guild_id, label, activity, start_hour, start_minute, end_hour, end_minute, timezone):
    """Creates a new reminder, or updates the existing one with the same label.
    Updating preserves in-progress window/streak state; only a brand new reminder starts blank."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM reminders WHERE user_id = ? AND guild_id = ? AND label = ?",
            (user_id, guild_id, label),
        ).fetchone()
        if existing:
            reminder_id = existing["id"]
            conn.execute(
                """UPDATE reminders SET activity = ?, start_hour = ?, start_minute = ?,
                   end_hour = ?, end_minute = ?, timezone = ? WHERE id = ?""",
                (activity, start_hour, start_minute, end_hour, end_minute, timezone, reminder_id),
            )
        else:
            cur = conn.execute(
                """INSERT INTO reminders
                   (user_id, guild_id, label, activity, start_hour, start_minute, end_hour, end_minute,
                    timezone, last_start_date, last_nudge_date, last_result_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)""",
                (user_id, guild_id, label, activity, start_hour, start_minute, end_hour, end_minute, timezone),
            )
            reminder_id = cur.lastrowid
            conn.execute(
                "INSERT INTO streaks (reminder_id, current_streak, longest_streak, last_checkin_date) VALUES (?, 0, 0, NULL)",
                (reminder_id,),
            )
        return reminder_id


def delete_reminder(user_id, guild_id, label):
    """Permanently removes the reminder, its streak, and any pending checkins. Returns True if it existed."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM reminders WHERE user_id = ? AND guild_id = ? AND label = ?",
            (user_id, guild_id, label),
        ).fetchone()
        if row is None:
            return False
        reminder_id = row["id"]
        conn.execute("DELETE FROM pending_checkins WHERE reminder_id = ?", (reminder_id,))
        conn.execute("DELETE FROM streaks WHERE reminder_id = ?", (reminder_id,))
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        return True


def get_all_reminders():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM reminders").fetchall()


def get_reminder(user_id, guild_id, label):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND guild_id = ? AND label = ?",
            (user_id, guild_id, label),
        ).fetchone()


def get_user_reminders(user_id, guild_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND guild_id = ? ORDER BY label",
            (user_id, guild_id),
        ).fetchall()


def get_user_reminders_with_streaks(user_id, guild_id):
    with get_conn() as conn:
        return conn.execute(
            """SELECT r.*, s.current_streak, s.longest_streak, s.last_checkin_date
               FROM reminders r JOIN streaks s ON s.reminder_id = r.id
               WHERE r.user_id = ? AND r.guild_id = ?
               ORDER BY r.label""",
            (user_id, guild_id),
        ).fetchall()


def get_streak(reminder_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM streaks WHERE reminder_id = ?", (reminder_id,)
        ).fetchone()


def mark_reminder_started(reminder_id, date_str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET last_start_date = ? WHERE id = ?",
            (date_str, reminder_id),
        )


def mark_reminder_nudged(reminder_id, date_str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET last_nudge_date = ? WHERE id = ?",
            (date_str, reminder_id),
        )


def mark_reminder_resolved(reminder_id, date_str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET last_result_date = ? WHERE id = ?",
            (date_str, reminder_id),
        )


def reset_streak(reminder_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE streaks SET current_streak = 0 WHERE reminder_id = ?",
            (reminder_id,),
        )


def record_checkin(reminder_id, date_str):
    """Returns the new current_streak, or None if already checked in for this date."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT current_streak, longest_streak, last_checkin_date FROM streaks WHERE reminder_id = ?",
            (reminder_id,),
        ).fetchone()
        if row is None or row["last_checkin_date"] == date_str:
            return None
        new_current = row["current_streak"] + 1
        new_longest = max(new_current, row["longest_streak"])
        conn.execute(
            "UPDATE streaks SET current_streak = ?, longest_streak = ?, last_checkin_date = ? WHERE reminder_id = ?",
            (new_current, new_longest, date_str, reminder_id),
        )
        return new_current


def add_pending_checkin(message_id, reminder_id, date_str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pending_checkins (message_id, reminder_id, date) VALUES (?, ?, ?)",
            (message_id, reminder_id, date_str),
        )


def get_pending_checkin(message_id):
    with get_conn() as conn:
        return conn.execute(
            """SELECT pc.message_id, pc.reminder_id, pc.date, r.user_id, r.guild_id, r.label, r.activity
               FROM pending_checkins pc JOIN reminders r ON r.id = pc.reminder_id
               WHERE pc.message_id = ?""",
            (message_id,),
        ).fetchone()


def get_leaderboard(guild_id, limit=20):
    with get_conn() as conn:
        return conn.execute(
            """SELECT r.user_id, r.label, r.activity, s.current_streak, s.longest_streak
               FROM streaks s JOIN reminders r ON r.id = s.reminder_id
               WHERE r.guild_id = ? ORDER BY s.current_streak DESC, s.longest_streak DESC LIMIT ?""",
            (guild_id, limit),
        ).fetchall()
