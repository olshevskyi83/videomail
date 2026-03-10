import os
import logging
import requests
from flask import Flask, request, jsonify, abort

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("notify-bot")

BOT_TOKEN = os.getenv("NOTIFY_BOT_TOKEN", "").strip()
AUTH_TOKEN = os.getenv("NOTIFY_AUTH_TOKEN", "").strip()
DEFAULT_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "").strip()  # можна не вказувати, тоді треба присилати chat_id у запиті
PORT = int(os.getenv("PORT", "8088"))

if not BOT_TOKEN:
    log.error("NOTIFY_BOT_TOKEN must be set")
    # не падаємо в нуль, але сенсу небагато

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify(ok=True)

def _require_auth():
    # якщо AUTH_TOKEN заданий — перевіряємо заголовок
    if AUTH_TOKEN:
        token_hdr = request.headers.get("X-Notify-Token", "")
        if token_hdr != AUTH_TOKEN:
            abort(401)

def _send_text(chat_id: str, text: str):
    url = f"{TELEGRAM_API}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=8)
        r.raise_for_status()
    except Exception as e:
        log.exception("sendMessage failed: %s", e)
        raise

@app.post("/notify")
def notify():
    _require_auth()
    js = request.get_json(force=True, silent=True) or {}
    text = (js.get("text") or "").strip()
    chat_id = str(js.get("chat_id") or DEFAULT_CHAT_ID).strip()
    if not text or not chat_id:
        abort(400, "text and chat_id required")
    _send_text(chat_id, text)
    return jsonify(ok=True)

if __name__ == "__main__":
    # Прямий запуск (в контейнері все одно через CMD)
    app.run(host="0.0.0.0", port=PORT)
