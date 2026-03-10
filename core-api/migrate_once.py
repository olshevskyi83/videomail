#!/usr/bin/env python3
import os, sys, re, sqlite3

def parse_sqlite_path(database_url: str | None) -> str | None:
    if not database_url:
        return None
    m1 = re.match(r"^sqlite:///(.+)$", database_url)   # 3 слеші: відносний від /app
    m2 = re.match(r"^sqlite:////(.+)$", database_url)  # 4 слеші: абсолютний шлях
    if m2:
        return "/" + m2.group(1).lstrip("/")
    if m1:
        # відносний шлях від робочої теки контейнера, зазвичай /app
        base = os.getcwd()
        return os.path.normpath(os.path.join(base, m1.group(1)))
    return None

def detect_sqlite_path() -> str | None:
    # 1) з DATABASE_URL
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("SQLALCHEMY_DATABASE_URL")
    if db_url:
        if db_url.startswith("postgresql") or db_url.startswith("postgres"):
            print("Postgres detected. No SQLite migration needed.")
            return None
        p = parse_sqlite_path(db_url)
        if p:
            return p

    # 2) типові місця в твоєму проекті
    candidates = [
        "/app/data/app.db",
        "/app/core-api/data/app.db",
        "/app/core-api/data/data.db",
        "/app/data/data.db",
        "/srv/videomail/data/app.db",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # 3) легкий пошук у межах /app
    for root, dirs, files in os.walk("/app"):
        for f in files:
            if f.endswith(".db") or f.endswith(".sqlite") or f.endswith(".sqlite3"):
                return os.path.join(root, f)
    return None

DDL = [
    # videos
    ("videos", "target",         "ALTER TABLE videos ADD COLUMN target TEXT"),
    ("videos", "published_at",   "ALTER TABLE videos ADD COLUMN published_at DATETIME"),
    ("videos", "delivered_to_tg","ALTER TABLE videos ADD COLUMN delivered_to_tg BOOLEAN DEFAULT 0"),
    # users
    ("users",  "tg_chat_id",     "ALTER TABLE users ADD COLUMN tg_chat_id INTEGER"),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_videos_status_target ON videos(status, target)",
    "CREATE INDEX IF NOT EXISTS ix_videos_user_status ON videos(user_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_support_user_key ON support_messages(user_key)",
]

def has_column(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def run_migration(db_path: str):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    for table, col, stmt in DDL:
        try:
            if not has_column(cur, table, col):
                cur.execute(stmt)
        except sqlite3.OperationalError as e:
            # якщо колонки вже є або таблиці поки нема — не падаємо
            print(f"Skip {table}.{col}: {e}")

    for stmt in INDEXES:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError as e:
            print(f"Skip index: {e}")

    con.commit()
    con.close()

def main():
    db_path = detect_sqlite_path()
    if not db_path:
        print("No SQLite DB found or Postgres in use.")
        sys.exit(0)
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        sys.exit(1)
    print(f"Migrating: {db_path}")
    run_migration(db_path)
    print("Migration OK")

if __name__ == "__main__":
    main()
