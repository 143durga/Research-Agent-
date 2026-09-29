"""
SQLite connection management and migration runner for Researcher Agent.

Design notes:
- SQLite was chosen so the app runs locally with zero external database
  setup (per the "must run locally after installation" requirement).
- Migrations are plain, ordered .sql files in db/migrations/. Each file is
  applied at most once; applied versions are tracked in schema_migrations.
- Foreign keys are enforced (PRAGMA foreign_keys=ON) on every connection.
"""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DB_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "instance" / "researcher_agent.db"))


def get_connection():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_cursor(commit: bool = False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def run_migrations(verbose: bool = True):
    """Apply any .sql files in migrations/ that haven't been applied yet, in filename order."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()

    applied = {row["version"] for row in cur.execute("SELECT version FROM schema_migrations")}
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for path in migration_files:
        version = path.name
        if version in applied:
            continue
        sql = path.read_text()
        cur.executescript(sql)
        cur.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()
        if verbose:
            print(f"[migrations] applied {version}")

    # Ensure a default local user exists (single-user local app).
    cur.execute("SELECT id FROM users LIMIT 1")
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users (email, name) VALUES (?, ?)",
            ("researcher@local", "Researcher"),
        )
        conn.commit()
        if verbose:
            print("[migrations] created default local user")

    conn.close()


def get_default_user_id() -> int:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
        row = cur.fetchone()
        return row["id"] if row else 1


def reset_database():
    """Destructive: deletes the sqlite file. Used only by tests / dev reset."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    run_migrations(verbose=False)
