import json
import sqlite3
import time
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    full_name TEXT,
    username TEXT,
    joined_at INTEGER
);
CREATE TABLE IF NOT EXISTS tests (
    code INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    -- answers: JSON ro'yxat. Har biri {"type":"choice","value":"a"} yoki {"type":"open","values":["1/2","0.5"]}
    answers TEXT NOT NULL,
    options INTEGER NOT NULL DEFAULT 4,      -- 4 => A-D, 5 => A-E
    math_keyboard INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    owner_id INTEGER,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_code INTEGER NOT NULL,
    tg_id INTEGER NOT NULL,
    given TEXT NOT NULL,
    correct_count INTEGER NOT NULL,
    total INTEGER NOT NULL,
    created_at INTEGER,
    UNIQUE(test_code, tg_id)
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def upsert_user(tg_id, full_name, username):
    with conn() as c:
        c.execute(
            "INSERT INTO users(tg_id, full_name, username, joined_at) VALUES(?,?,?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET full_name=excluded.full_name, username=excluded.username",
            (tg_id, full_name, username, int(time.time())),
        )


def create_test(title, answers, options=4, math_keyboard=False, owner_id=None):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO tests(title, answers, options, math_keyboard, owner_id, created_at) VALUES(?,?,?,?,?,?)",
            (title, json.dumps(answers), options, int(math_keyboard), owner_id, int(time.time())),
        )
        return cur.lastrowid


def update_test(code, title, answers, options, math_keyboard, is_active):
    with conn() as c:
        c.execute(
            "UPDATE tests SET title=?, answers=?, options=?, math_keyboard=?, is_active=? WHERE code=?",
            (title, json.dumps(answers), options, int(math_keyboard), int(is_active), code),
        )


def delete_test(code):
    with conn() as c:
        c.execute("DELETE FROM submissions WHERE test_code=?", (code,))
        c.execute("DELETE FROM tests WHERE code=?", (code,))


def get_test(code):
    with conn() as c:
        r = c.execute("SELECT * FROM tests WHERE code=?", (code,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["answers"] = json.loads(d["answers"])
    return d


def list_tests():
    with conn() as c:
        rows = c.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM submissions s WHERE s.test_code=t.code) AS subs "
            "FROM tests t ORDER BY t.code DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["total"] = len(json.loads(d["answers"]))
        out.append(d)
    return out


def get_submission(code, tg_id):
    with conn() as c:
        r = c.execute("SELECT * FROM submissions WHERE test_code=? AND tg_id=?", (code, tg_id)).fetchone()
    return dict(r) if r else None


def save_submission(code, tg_id, given, correct, total):
    """Faqat bir marta javob berish mumkin. Muvaffaqiyatli bo'lsa True."""
    with conn() as c:
        try:
            c.execute(
                "INSERT INTO submissions(test_code, tg_id, given, correct_count, total, created_at) VALUES(?,?,?,?,?,?)",
                (code, tg_id, json.dumps(given), correct, total, int(time.time())),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def results_for(code):
    with conn() as c:
        rows = c.execute(
            "SELECT s.*, u.full_name, u.username FROM submissions s "
            "LEFT JOIN users u ON u.tg_id=s.tg_id WHERE s.test_code=? "
            "ORDER BY s.correct_count DESC, s.created_at ASC",
            (code,),
        ).fetchall()
    return [dict(r) for r in rows]


def reset_submission(code, tg_id):
    with conn() as c:
        c.execute("DELETE FROM submissions WHERE test_code=? AND tg_id=?", (code, tg_id))


def list_users():
    with conn() as c:
        rows = c.execute(
            "SELECT u.*, (SELECT COUNT(*) FROM submissions s WHERE s.tg_id=u.tg_id) AS subs "
            "FROM users u ORDER BY u.joined_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def stats():
    with conn() as c:
        return {
            "users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "tests": c.execute("SELECT COUNT(*) FROM tests").fetchone()[0],
            "submissions": c.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],
        }
