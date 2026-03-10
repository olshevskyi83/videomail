# Installation Guide

This guide installs Videomail in about **5 minutes** on a Linux server.

Requirements:

- Docker
- Docker Compose
- Linux server (Ubuntu / Debian recommended)

---

# 1 Clone repository
git clone https://github.com/yourname/videomail.git

cd videomail


---

# 2 Configure environment

Create `.env`


BASE_DIR=/srv/videomail

ADMIN_BEARER_TOKEN=yourtoken

NOTIFY_AUTH_TOKEN=token
NOTIFY_CHAT_ID=telegram_chat_id

TG_BOT_TOKEN=telegram_bot_token
TG_CHAT_ID=telegram_chat_id


---

# 3 Create storage directories


sudo mkdir -p /srv/videomail/{inbox,review,published}


---

# 4 Start services


docker compose up -d


---

# 5 Check services


docker compose ps


Health check


curl http://localhost:8000/health


---

# Admin panel


https://admin.yourdomain


---

# User kiosk


https://kiosk.yourdomain
