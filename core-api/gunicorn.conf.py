import os
bind = "0.0.0.0:8000"
db_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or "sqlite:////srv/videomail/videomail.db"
workers = 1 if db_url.startswith("sqlite") else 2
timeout = 180
