# Videomail

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![Flask](https://img.shields.io/badge/flask-backend-black)
![License](https://img.shields.io/badge/license-MIT-green)

Videomail is a modular video messaging platform that allows users to record and send video messages through a **web kiosk interface**, while relatives communicate through **Telegram bots**.

The system includes:

- browser video recording
- moderation panel
- Telegram integration
- notification system
- fully containerized architecture (Docker)

Videomail is designed as a **microservice-style system** with separate services for API, UI, moderation, and bots.

---

# Architecture

![Architecture](docs/architecture.png)

Main services:

- **core-api** — backend API
- **admin-panel** — moderation UI
- **user-ui** — kiosk interface
- **family-bot** — Telegram bot for relatives
- **notify-bot** — system notifications
- **reverse-proxy** — nginx routing

---

# Features

- Browser video recording
- Moderation workflow
- Telegram integration
- Notification system
- Support chat
- Docker deployment
- Kiosk interface

---

# Project Structure
videomail/
│
├── admin-panel/
│ ├── app.py
│ └── templates/
│
├── bots/
│ ├── family-bot/
│ │ └── family_bot.py
│ │
│ └── notify-bot/
│ └── notify_bot.py
│
├── core-api/
│ └── app.py
│
├── user-ui/
│ ├── ui.html
│ ├── app.js
│ └── style.css
│
├── docker-compose.yml
├── videomail.sh
└── .env

---

# Components

## Core API

Main backend service.

Technology stack:

- Flask
- SQLAlchemy
- Gunicorn

Default port:
8000

Storage structure:
/srv/videomail
inbox/
review/
published/


Database:
SQLlite (default)

---

## Admin Panel

Moderation interface for administrators.

Features:

- user management
- video moderation
- support tickets
- content review

Authentication:
Authorization: Bearer ADMIN_BEARER_TOKEN

---

## User UI (Kiosk)

Frontend interface used by users.

Features:

- login via Nick + Code
- video recording
- video inbox
- support chat
- instructions tab

Tabs:
Recorder
Inbox
Support
Instructions

---

## Family Bot

Telegram bot used by relatives.

Capabilities:

- receive video messages
- upload them to core-api
- add them to moderation queue

---

## Notify Bot

Notification microservice.

Endpoint:
POST /notify

Headers
X-Notify-Token


Body example
{
"text": "New video uploaded",
"chat_id": "123456"
}

Used for:

- moderation alerts
- support messages
- system events

---

# API

## Health
GET /health
GET /api/v1/ping


---

## Users

| Method | Endpoint |
|------|------|
GET | /api/v1/admin/users  
POST | /api/v1/admin/users  
PUT | /api/v1/admin/users/{id}  
DELETE | /api/v1/admin/users/{id}

---

## Media

| Method | Endpoint |
|------|------|
GET | /api/v1/admin/media/inbox  
GET | /api/v1/admin/media/review  
GET | /api/v1/admin/media/published  

---

## Support

| Method | Endpoint |
|------|------|
GET | /api/v1/admin/support

---

# Environment Variables


BASE_DIR=/srv/videomail

ADMIN_BEARER_TOKEN=

CORE_PUBLIC_URL=http://core-api:8000

NOTIFY_BOT_URL=http://notify-bot:8088

NOTIFY_AUTH_TOKEN=

NOTIFY_CHAT_ID=

TG_BOT_TOKEN=
TG_CHAT_ID=


---

# Deployment

See:


INSTALL.md


---

# Backup

User files are stored in:


/srv/videomail


Backup example:


tar -czf videomail-backup.tar.gz /srv/videomail


---

# Roadmap

Future improvements:

- PostgreSQL support
- S3 storage
- mobile UI
- WebRTC streaming
- push notifications
- multi-tenant architecture

---

# License

MIT License
