import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import httpx
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================
# Конфіг
# =========================
FAMILY_BOT_TOKEN = os.environ.get("FAMILY_BOT_TOKEN", "")
CORE_API_URL = os.environ.get("CORE_API_URL", "http://core-api:8000").rstrip("/")
BASE_DIR = Path(os.environ.get("BASE_DIR", "/srv/videomail"))
LATEST_LIMIT = int(os.environ.get("LATEST_LIMIT", "5"))
STATE_PATH = Path(os.environ.get("FAMILY_BOT_STATE", "/data/family_state.json"))

CACHE_DIR = STATE_PATH.parent / "cache"
UPLOADS_DIR = STATE_PATH.parent / "uploads"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("family-bot")

# Етапи діалогу
ASK_NICK, ASK_CODE = range(2)

# Кнопки меню
BTN_INBOX = "Inbox"
BTN_HELP = "Інструкції"
BTN_SWITCH = "Змінити користувача"

MAIN_KB = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_INBOX)], [KeyboardButton(BTN_HELP)], [KeyboardButton(BTN_SWITCH)]],
    resize_keyboard=True,
)

# =========================
# Стан (зв'язок чат -> user_key)
# =========================
def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {"links": {}}  # chat_id -> { user_key, nickname }

def save_state(state: Dict[str, Any]) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(STATE_PATH)

STATE = load_state()

def get_link(chat_id: int) -> Optional[Dict[str, str]]:
    return STATE.get("links", {}).get(str(chat_id))

def put_link(chat_id: int, user_key: str, nickname: str) -> None:
    STATE.setdefault("links", {})[str(chat_id)] = {"user_key": user_key, "nickname": nickname}
    save_state(STATE)

def drop_link(chat_id: int) -> None:
    if STATE.get("links", {}).pop(str(chat_id), None) is not None:
        save_state(STATE)

# =========================
# HTTP
# =========================
async def api_post(path: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    url = f"{CORE_API_URL}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(url, json=payload)
            data = r.json() if "application/json" in r.headers.get("content-type", "") else {}
            return (r.status_code == 200, data)
        except Exception as e:
            log.exception("POST %s failed: %s", url, e)
            return (False, {})

async def api_get(path: str, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    url = f"{CORE_API_URL}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(url, params=params)
            data = r.json() if "application/json" in r.headers.get("content-type", "") else {}
            return (r.status_code == 200, data)
        except Exception as e:
            log.exception("GET %s failed: %s", url, e)
            return (False, {})

# =========================
# FFmpeg → MP4
# =========================
def is_mp4(p: Path) -> bool:
    return p.suffix.lower() == ".mp4"

async def convert_to_mp4(src: Path) -> Path:
    dst = CACHE_DIR / (src.stem + ".mp4")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "baseline",
        "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst),
    ]
    log.info("FFmpeg: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(*cmd)
    rc = await proc.wait()
    if rc != 0 or not dst.exists():
        raise RuntimeError(f"ffmpeg failed rc={rc}")
    return dst

async def ensure_mp4(path: Path) -> Path:
    return path if is_mp4(path) else await convert_to_mp4(path)

# =========================
# Пошук файлу, який реально існує
# =========================
def pick_published_file(item: Dict[str, Any]) -> Optional[Path]:
    raw = (item.get("path") or item.get("file") or "").strip()
    if raw:
        p = Path(raw)
        if p.is_absolute() and p.exists():
            return p
        cand = (BASE_DIR / "published" / p.name)
        if cand.exists():
            return cand
    published_dir = BASE_DIR / "published"
    if published_dir.exists():
        files = sorted(published_dir.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)
        return files[0] if files else None
    return None

# =========================
# Хендлери
# =========================
async def start_login_flow(update: Update) -> int:
    await update.message.reply_text("Введіть логін:")
    return ASK_NICK

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    # За вимогою — завжди просимо логін і код. Старі прив'язки не заважають.
    return await start_login_flow(update)

async def cmd_switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    # Примусово перевʼязатися
    drop_link(update.effective_chat.id)
    return await start_login_flow(update)

async def on_nick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    nickname = (update.message.text or "").strip()
    if not nickname:
        await update.message.reply_text("Введіть логін:")
        return ASK_NICK
    ctx.user_data["nickname"] = nickname
    await update.message.reply_text("Введіть код:")
    return ASK_CODE

async def on_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    code = (update.message.text or "").strip()
    nickname = ctx.user_data.get("nickname", "")
    if not code or not nickname:
        await update.message.reply_text("Введіть логін:")
        return ASK_NICK

    ok, data = await api_post("/api/auth", {"nickname": nickname, "code": code})
    if not ok or not data.get("ok"):
        await update.message.reply_text("Невірно. Спробуйте /start")
        return ConversationHandler.END

    user_key = data.get("user_key")
    chat_id = update.effective_chat.id
    await api_post("/api/tg/link_chat", {"user_key": user_key, "chat_id": chat_id})
    put_link(chat_id, user_key, nickname)

    await update.message.reply_text("Готово.", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def show_instructions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Inbox — показати опубліковані відео саме привʼязаного користувача.\n"
        "Надішліть у чат відео — воно піде у його Inbox (після підтвердження адміном).",
        reply_markup=MAIN_KB,
    )

async def show_inbox(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    link = get_link(update.effective_chat.id)
    if not link:
        await update.message.reply_text("Спочатку авторизуйтесь: /start", reply_markup=MAIN_KB)
        return

    ok, data = await api_get("/api/published", {"user_key": link["user_key"], "target": "tg", "limit": LATEST_LIMIT})
    if not ok:
        await update.message.reply_text("Сервер недоступний.", reply_markup=MAIN_KB)
        return

    items: List[Dict[str, Any]] = data.get("items") or data.get("videos") or data.get("data") or []
    if not items:
        await update.message.reply_text("Порожньо.", reply_markup=MAIN_KB)
        return

    for item in items:
        f = pick_published_file(item)
        if not f or not f.exists():
            continue
        try:
            mp4 = await ensure_mp4(f)
            with open(mp4, "rb") as fh:
                await update.effective_chat.send_video(
                    video=InputFile(fh, filename=mp4.name),
                    supports_streaming=True,
                )
        except Exception as e:
            log.exception("send_video failed: %s", e)

async def on_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    link = get_link(update.effective_chat.id)
    if not link:
        await update.message.reply_text("Спочатку авторизуйтесь: /start", reply_markup=MAIN_KB)
        return

    tg_video = update.message.video or update.message.document
    if not tg_video:
        return

    file = await ctx.bot.get_file(tg_video.file_id)
    name = tg_video.file_name or f"{tg_video.file_unique_id}.mp4"
    local = UPLOADS_DIR / name
    await file.download_to_drive(str(local))

    path = local
    if not is_mp4(path):
        try:
            path = await ensure_mp4(path)
        except Exception:
            path = local

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            with open(path, "rb") as fh:
                files = {"file": (path.name, fh, "video/mp4")}
                data = {"user_key": link["user_key"], "target": "inbox", "source": "telegram"}
                r = await client.post(f"{CORE_API_URL}/api/upload", data=data, files=files)
        if r.status_code == 200:
            await update.message.reply_text("Надіслано.", reply_markup=MAIN_KB)
        else:
            await update.message.reply_text("Помилка завантаження.", reply_markup=MAIN_KB)
    except Exception as e:
        log.exception("upload failed: %s", e)
        await update.message.reply_text("Помилка завантаження.", reply_markup=MAIN_KB)

async def txt_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    t = (update.message.text or "").strip()
    tl = t.lower()
    if tl == BTN_INBOX.lower():
        await show_inbox(update, ctx)
    elif tl == BTN_HELP.lower():
        await show_instructions(update, ctx)
    elif tl == BTN_SWITCH.lower():
        await cmd_switch(update, ctx)
    else:
        await update.message.reply_text("Меню:", reply_markup=MAIN_KB)

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    drop_link(update.effective_chat.id)
    await update.message.reply_text("Скинуто. /start")

# =========================
# Main
# =========================
def main() -> None:
    if not FAMILY_BOT_TOKEN:
        raise SystemExit("FAMILY_BOT_TOKEN is not set")

    app = ApplicationBuilder().token(FAMILY_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Regex(f"^{BTN_SWITCH}$") & filters.TEXT, cmd_switch),
        ],
        states={
            ASK_NICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_nick)],
            ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_code)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    # Розкладка: спочатку діалог, потім решта
    app.add_handler(conv)
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, on_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, txt_router))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
