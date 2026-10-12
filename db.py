"""
db.py -- the only place that talks to the SQLite database.

Used by both the staff admin (admin/) and the robot (robot/), which run on the
same Windows PC and share one database file (default: data/guide.db).
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import bcrypt
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


class ValidationError(Exception):
    """A user-facing error. The message is Hebrew and safe to show in the UI."""


def _default_db_path() -> Path:
    p = Path(os.environ.get("DB_PATH", "data/guide.db"))
    return p if p.is_absolute() else PROJECT_ROOT / p


_db_path: Path = _default_db_path()


def set_db_path(path) -> None:
    """Point the module at another database file (used by tests)."""
    global _db_path
    _db_path = Path(path)


def get_db_path() -> Path:
    return _db_path


@contextmanager
def connect():
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(value):
    """Trim strings; turn empty strings into None."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def _one(cursor):
    r = cursor.fetchone()
    return dict(r) if r else None


# --------------------------------------------------------------------------- schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gestures (
    id   INTEGER PRIMARY KEY,          -- = robot action-group number
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS places (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    aliases    TEXT,                   -- comma-separated
    floor      TEXT,
    directions TEXT,
    gesture_id INTEGER REFERENCES gestures(id),
    is_active  INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS knowledge_items (
    id          INTEGER PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id),
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT,
    updated_by  INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT,
    lecturer    TEXT,
    date        TEXT NOT NULL,         -- YYYY-MM-DD
    start_time  TEXT NOT NULL,         -- HH:MM
    end_time    TEXT NOT NULL,         -- HH:MM
    place_id    INTEGER REFERENCES places(id),
    is_active   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS unanswered_questions (
    id            INTEGER PRIMARY KEY,
    question_text TEXT NOT NULL,
    asked_at      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new'   -- 'new' | 'handled'
);
"""

SEED_GESTURES = [
    (124, "הצבעה לשירותים"),
    (125, "הצבעה לחדר עיון"),
    (126, "הצבעה למעליות"),
    (127, "הצבעה לחדר סגל"),
]
SEED_PLACES = [
    ("שירותים", 124),
    ("חדר עיון", 125),
    ("מעליות", 126),
    ("חדר סגל", 127),
    ("מזכירות", None),
]
SEED_CATEGORIES = ["מסלולי לימוד", "שכר לימוד", "מלגות", "כללי"]
# The three fixed answers that used to live in MENU_OPTIONS (academy_guide.py).
SEED_KNOWLEDGE = [
    (
        "מסלולי לימוד",
        "אילו מסלולי לימוד יש במכללה?",
        "במכללה האקדמית תל אביב יפו אפשר ללמוד מדעי המחשב, מערכות מידע, פסיכולוגיה, "
        "כלכלה וניהול, מדעי הסיעוד, וממשל וחברה, לתואר ראשון ושני.",
    ),
    (
        "שכר לימוד",
        "כמה עולה שכר הלימוד?",
        "שכר הלימוד במכללה האקדמית תל אביב יפו נקבע על ידי המועצה להשכלה גבוהה, "
        "וזהה לשכר הלימוד באוניברסיטאות.",
    ),
    (
        "מלגות",
        "אילו מלגות יש במכללה?",
        "המכללה מציעה ארבעה סוגי מלגות: למצטיינים, לבעלי נתוני קבלה גבוהים, "
        "מלגות סיוע כלכלי, ומלגות לעידוד מעורבות חברתית.",
    ),
]


def init_db(seed: bool = True) -> None:
    """Create missing tables and insert seed rows that are not there yet. Safe to re-run."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        if not seed:
            return
        for gid, name in SEED_GESTURES:
            conn.execute("INSERT OR IGNORE INTO gestures (id, name) VALUES (?, ?)", (gid, name))
        for name, gid in SEED_PLACES:
            conn.execute(
                "INSERT OR IGNORE INTO places (name, gesture_id, is_active, updated_at) VALUES (?, ?, 1, ?)",
                (name, gid, _now()),
            )
        for name in SEED_CATEGORIES:
            conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        for cat, question, answer in SEED_KNOWLEDGE:
            exists = conn.execute("SELECT 1 FROM knowledge_items WHERE question = ?", (question,)).fetchone()
            if not exists:
                cid = conn.execute("SELECT id FROM categories WHERE name = ?", (cat,)).fetchone()["id"]
                conn.execute(
                    "INSERT INTO knowledge_items (category_id, question, answer, is_active, updated_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (cid, question, answer, _now()),
                )


# --------------------------------------------------------------------------- users

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_user(username: str, password: str, full_name: str = None) -> int:
    username = _clean(username)
    if not username or not password:
        raise ValidationError("יש למלא שם משתמש וסיסמה.")
    if len(password) < 6:
        raise ValidationError("הסיסמה צריכה להכיל לפחות 6 תווים.")
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, full_name, created_at) VALUES (?, ?, ?, ?)",
                (username, hash_password(password), _clean(full_name), _now()),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("שם המשתמש כבר קיים.")


def authenticate(username: str, password: str):
    """Return the user dict if the credentials are right, else None."""
    with connect() as conn:
        user = _one(conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)))
    if user and bcrypt.checkpw((password or "").encode("utf-8"), user["password_hash"].encode("utf-8")):
        return user
    return None


def get_user(user_id: int):
    with connect() as conn:
        return _one(conn.execute("SELECT id, username, full_name, created_at FROM users WHERE id = ?", (user_id,)))


def list_users():
    with connect() as conn:
        return _rows(conn.execute("SELECT id, username, full_name, created_at FROM users ORDER BY username"))


def change_password(user_id: int, new_password: str) -> None:
    if not new_password or len(new_password) < 6:
        raise ValidationError("הסיסמה צריכה להכיל לפחות 6 תווים.")
    with connect() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))


# --------------------------------------------------------------------------- gestures

def list_gestures():
    with connect() as conn:
        return _rows(conn.execute("SELECT * FROM gestures ORDER BY id"))


# --------------------------------------------------------------------------- places

def list_places(active_only: bool = False):
    sql = (
        "SELECT p.*, g.name AS gesture_name FROM places p "
        "LEFT JOIN gestures g ON g.id = p.gesture_id"
    )
    if active_only:
        sql += " WHERE p.is_active = 1"
    with connect() as conn:
        return _rows(conn.execute(sql + " ORDER BY p.name"))


def get_place(place_id: int):
    with connect() as conn:
        return _one(conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)))


def _place_values(data: dict):
    name = _clean(data.get("name"))
    if not name:
        raise ValidationError("יש למלא שם מקום.")
    gesture_id = data.get("gesture_id")
    gesture_id = int(gesture_id) if gesture_id not in (None, "", "0", 0) else None
    aliases = _clean(data.get("aliases"))
    if aliases:
        aliases = ", ".join(a.strip() for a in aliases.split(",") if a.strip())
    return (
        name,
        aliases,
        _clean(data.get("floor")),
        _clean(data.get("directions")),
        gesture_id,
        1 if data.get("is_active") else 0,
        _now(),
    )


def create_place(data: dict) -> int:
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO places (name, aliases, floor, directions, gesture_id, is_active, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                _place_values(data),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("כבר קיים מקום בשם הזה.")


def update_place(place_id: int, data: dict) -> None:
    try:
        with connect() as conn:
            conn.execute(
                "UPDATE places SET name = ?, aliases = ?, floor = ?, directions = ?, gesture_id = ?, "
                "is_active = ?, updated_at = ? WHERE id = ?",
                (*_place_values(data), place_id),
            )
    except sqlite3.IntegrityError:
        raise ValidationError("כבר קיים מקום בשם הזה.")


def delete_place(place_id: int) -> None:
    with connect() as conn:
        used = conn.execute("SELECT COUNT(*) FROM events WHERE place_id = ?", (place_id,)).fetchone()[0]
        if used:
            raise ValidationError(
                f"אי אפשר למחוק את המקום: הוא משויך ל-{used} אירועים בלוח הזמנים. "
                "אפשר לסמן אותו כלא פעיל, או לשנות קודם את מקום האירועים."
            )
        conn.execute("DELETE FROM places WHERE id = ?", (place_id,))


# --------------------------------------------------------------------------- categories

def list_categories():
    with connect() as conn:
        return _rows(conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM knowledge_items k WHERE k.category_id = c.id) AS item_count "
            "FROM categories c ORDER BY c.name"
        ))


def create_category(name: str) -> int:
    name = _clean(name)
    if not name:
        raise ValidationError("יש למלא שם קטגוריה.")
    try:
        with connect() as conn:
            return conn.execute("INSERT INTO categories (name) VALUES (?)", (name,)).lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("כבר קיימת קטגוריה בשם הזה.")


def delete_category(category_id: int) -> None:
    with connect() as conn:
        used = conn.execute("SELECT COUNT(*) FROM knowledge_items WHERE category_id = ?", (category_id,)).fetchone()[0]
        if used:
            raise ValidationError(f"אי אפשר למחוק את הקטגוריה: יש בה {used} פריטים.")
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


# --------------------------------------------------------------------------- knowledge items

def list_knowledge(category_id=None, search: str = None, active_only: bool = False):
    sql = (
        "SELECT k.*, c.name AS category_name FROM knowledge_items k "
        "LEFT JOIN categories c ON c.id = k.category_id WHERE 1 = 1"
    )
    params = []
    if category_id:
        sql += " AND k.category_id = ?"
        params.append(int(category_id))
    if search and search.strip():
        sql += " AND (k.question LIKE ? OR k.answer LIKE ?)"
        like = f"%{search.strip()}%"
        params += [like, like]
    if active_only:
        sql += " AND k.is_active = 1"
    with connect() as conn:
        return _rows(conn.execute(sql + " ORDER BY c.name, k.question", params))


def get_knowledge(item_id: int):
    with connect() as conn:
        return _one(conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (item_id,)))


def _knowledge_values(data: dict, user_id=None):
    question, answer = _clean(data.get("question")), _clean(data.get("answer"))
    if not question or not answer:
        raise ValidationError("יש למלא שאלה ותשובה.")
    category_id = data.get("category_id")
    category_id = int(category_id) if category_id not in (None, "", "0", 0) else None
    return (category_id, question, answer, 1 if data.get("is_active") else 0, _now(), user_id)


def create_knowledge(data: dict, user_id=None) -> int:
    with connect() as conn:
        return conn.execute(
            "INSERT INTO knowledge_items (category_id, question, answer, is_active, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            _knowledge_values(data, user_id),
        ).lastrowid


def update_knowledge(item_id: int, data: dict, user_id=None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE knowledge_items SET category_id = ?, question = ?, answer = ?, is_active = ?, "
            "updated_at = ?, updated_by = ? WHERE id = ?",
            (*_knowledge_values(data, user_id), item_id),
        )


def delete_knowledge(item_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM knowledge_items WHERE id = ?", (item_id,))


# --------------------------------------------------------------------------- events

def list_events():
    with connect() as conn:
        return _rows(conn.execute(
            "SELECT e.*, p.name AS place_name FROM events e LEFT JOIN places p ON p.id = e.place_id "
            "ORDER BY e.date, e.start_time"
        ))


def get_event(event_id: int):
    with connect() as conn:
        return _one(conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)))


def _valid_time(t):
    try:
        datetime.strptime(t, "%H:%M")
        return True
    except (TypeError, ValueError):
        return False


def _event_values(data: dict):
    title = _clean(data.get("title"))
    date = _clean(data.get("date"))
    start, end = _clean(data.get("start_time")), _clean(data.get("end_time"))
    if not title or not date or not start or not end:
        raise ValidationError("יש למלא כותרת, תאריך, שעת התחלה ושעת סיום.")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("תאריך לא תקין.")
    if not (_valid_time(start) and _valid_time(end)):
        raise ValidationError("שעה לא תקינה. יש להזין בפורמט HH:MM.")
    if end <= start:
        raise ValidationError("שעת הסיום חייבת להיות אחרי שעת ההתחלה.")
    place_id = data.get("place_id")
    place_id = int(place_id) if place_id not in (None, "", "0", 0) else None
    return (
        title, _clean(data.get("description")), _clean(data.get("lecturer")),
        date, start, end, place_id, 1 if data.get("is_active") else 0,
    )


def create_event(data: dict) -> int:
    with connect() as conn:
        return conn.execute(
            "INSERT INTO events (title, description, lecturer, date, start_time, end_time, place_id, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            _event_values(data),
        ).lastrowid


def update_event(event_id: int, data: dict) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE events SET title = ?, description = ?, lecturer = ?, date = ?, start_time = ?, "
            "end_time = ?, place_id = ?, is_active = ? WHERE id = ?",
            (*_event_values(data), event_id),
        )


def delete_event(event_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))


def todays_upcoming_events(now: datetime = None):
    """Active events of today whose end time has not passed yet."""
    now = now or datetime.now()
    with connect() as conn:
        return _rows(conn.execute(
            "SELECT e.*, p.name AS place_name FROM events e LEFT JOIN places p ON p.id = e.place_id "
            "WHERE e.is_active = 1 AND e.date = ? AND e.end_time > ? ORDER BY e.start_time",
            (now.strftime("%Y-%m-%d"), now.strftime("%H:%M")),
        ))


# --------------------------------------------------------------------------- unanswered questions

def add_unanswered(question_text: str) -> int:
    question_text = _clean(question_text)
    if not question_text:
        raise ValidationError("שאלה ריקה.")
    with connect() as conn:
        return conn.execute(
            "INSERT INTO unanswered_questions (question_text, asked_at, status) VALUES (?, ?, 'new')",
            (question_text, _now()),
        ).lastrowid


def list_unanswered(status: str = None, limit: int = None):
    sql = "SELECT * FROM unanswered_questions"
    params = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY asked_at DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect() as conn:
        return _rows(conn.execute(sql, params))


def get_unanswered(qid: int):
    with connect() as conn:
        return _one(conn.execute("SELECT * FROM unanswered_questions WHERE id = ?", (qid,)))


def set_unanswered_status(qid: int, status: str) -> None:
    if status not in ("new", "handled"):
        raise ValueError(status)
    with connect() as conn:
        conn.execute("UPDATE unanswered_questions SET status = ? WHERE id = ?", (status, qid))


def delete_unanswered(qid: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM unanswered_questions WHERE id = ?", (qid,))


# --------------------------------------------------------------------------- dashboard

def dashboard_counts(now: datetime = None):
    now = now or datetime.now()
    with connect() as conn:
        one = lambda sql, *p: conn.execute(sql, p).fetchone()[0]
        return {
            "places": one("SELECT COUNT(*) FROM places WHERE is_active = 1"),
            "knowledge": one("SELECT COUNT(*) FROM knowledge_items WHERE is_active = 1"),
            "events_today": one(
                "SELECT COUNT(*) FROM events WHERE is_active = 1 AND date = ?", now.strftime("%Y-%m-%d")
            ),
            "unanswered_new": one("SELECT COUNT(*) FROM unanswered_questions WHERE status = 'new'"),
        }


# --------------------------------------------------------------------------- robot

def robot_snapshot(now: datetime = None):
    """Everything the robot may use to answer one question."""
    return {
        "places": list_places(active_only=True),
        "knowledge": list_knowledge(active_only=True),
        "events": todays_upcoming_events(now),
    }
