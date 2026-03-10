import os
import uuid
import mimetypes
import secrets
import shutil
from functools import wraps
from datetime import datetime as dt
import requests
from flask import Flask, request, jsonify, send_file, abort, redirect
from werkzeug.utils import secure_filename
from sqlalchemy import select
from werkzeug.datastructures import ImmutableMultiDict
from db import SessionLocal, engine
from models import Base, User, Session as S, Video, SupportTicket
from threading import Thread

app = Flask(__name__)
app.url_map.strict_slashes = False

BASE_DIR = os.getenv("BASE_DIR") or "/srv/videomail"
REVIEW_DIR = os.path.join(BASE_DIR, "review")
PUBLISHED_DIR = os.path.join(BASE_DIR, "published")
INBOX_DIR = os.path.join(BASE_DIR, "inbox")
os.makedirs(REVIEW_DIR, exist_ok=True)
os.makedirs(PUBLISHED_DIR, exist_ok=True)
os.makedirs(INBOX_DIR, exist_ok=True)

ADMIN_BEARER_TOKEN = os.getenv("ADMIN_BEARER_TOKEN", "changeme")

CORE_PUBLIC_URL = (os.getenv("CORE_PUBLIC_URL") or "").rstrip("/")

NOTIFY_BOT_URL = (os.getenv("NOTIFY_BOT_URL") or "").rstrip("/")
NOTIFY_AUTH_TOKEN = os.getenv("NOTIFY_AUTH_TOKEN", "")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID", "").strip()

SUPPORT_BOT_URL = (os.getenv("SUPPORT_BOT_URL") or "").strip()
SUPPORT_NOTIFY_SECRET = (os.getenv("SUPPORT_NOTIFY_SECRET") or "").strip()

Base.metadata.create_all(bind=engine, checkfirst=True)

# ------------------- helpers -------------------
def _session():
    return SessionLocal()

def _user_by_key(db, user_key: str) -> User:
    if not user_key:
        abort(400, "user_key required")
    u = db.execute(select(User).where(User.user_key == user_key)).scalars().first()
    if not u:
        abort(404, "user not found")
    if hasattr(u, "enabled") and not u.enabled:
        abort(403, "user disabled")
    return u

def _user_by_nickname(db, nickname: str) -> User | None:
    return db.execute(select(User).where(User.nickname == nickname)).scalars().first()

def _ext_from_mime(m: str | None) -> str:
    if not m:
        return ".webm"
    ext = mimetypes.guess_extension(m)
    return ext or (".webm" if "webm" in m else ".mp4")

def _safe_join(*parts) -> str:
    path = os.path.realpath(os.path.join(*parts))
    base = os.path.realpath(BASE_DIR)
    if not path.startswith(base + os.sep) and path != base:
        abort(400, "invalid path")
    return path

def _absolute(path: str) -> str:
    return f"{CORE_PUBLIC_URL}{path}" if CORE_PUBLIC_URL else path

def _public_file_url(video_id: int, user_key: str | None = None) -> str:
    qs = f"?user_key={user_key}" if user_key else ""
    return _absolute(f"/api/u/file/{video_id}{qs}")

def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not ADMIN_BEARER_TOKEN or auth != f"Bearer {ADMIN_BEARER_TOKEN}":
            abort(401)
        return fn(*args, **kwargs)
    return wrapper

def _move_to_final_if_needed(v: Video) -> None:
    p = getattr(v, "path", None)
    if not p:
        return
    if not os.path.isabs(p):
        p = os.path.join(BASE_DIR, p)
    final_dir = INBOX_DIR if (v.target == "inbox") else PUBLISHED_DIR
    if os.path.realpath(p).startswith(os.path.realpath(final_dir) + os.sep):
        v.path = p
        return
    if os.path.exists(p):
        new_path = _safe_join(final_dir, os.path.basename(p))
        shutil.move(p, new_path)
        v.path = new_path
    else:
        app.logger.warning("Video file missing on approve: %s", p)

#-------------------- forwarding helpers -------------------
def _forward_to(route: str, method: str, data: dict | ImmutableMultiDict | None = None):
    """
    Внутрішній форвардинг у межах Flask:
    - зберігаємо Authorization
    - підхоплюємо form/json payload і метод
    """
    headers = {}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth

    content_type = request.headers.get("Content-Type", "")
    json_payload = None
    form_payload = None

    if isinstance(data, ImmutableMultiDict):
        data = data.to_dict(flat=True)

    if request.files:
        form_payload = data or request.form.to_dict(flat=True)
        content_type = "application/x-www-form-urlencoded"
    else:
        if content_type.startswith("application/json") or (request.is_json and not request.form):
            json_payload = data if isinstance(data, dict) else (request.get_json(silent=True) or {})
            content_type = "application/json"
        else:
            form_payload = data if isinstance(data, dict) else request.form.to_dict(flat=True)
            content_type = "application/x-www-form-urlencoded"

    with app.test_request_context(
        route,
        method=method.upper(),
        headers=headers | {"Content-Type": content_type} if content_type else headers,
        data=form_payload if form_payload is not None else None,
        json=json_payload if json_payload is not None else None,
        query_string=request.args,
    ):
        return app.full_dispatch_request()

def _get_payload():
    if request.method == "GET":
        return request.args or {}
    if request.form:
        return request.form
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.args or {}

# ------------------- health -------------------
@app.get("/api/health")
def health():
    return jsonify(ok=True, time=dt.utcnow().isoformat())

# ==================== NOTIFY HELPERS (robust async) ====================
from threading import Thread
import requests
from requests.adapters import HTTPAdapter, Retry

def _notify__post(chat_id: int, text: str) -> None:
    """Синхронний POST у notify-bot з ретраями та адекватними таймаутами."""
    if not chat_id or not NOTIFY_BOT_URL:
        app.logger.info("notify: skip (no chat_id or NOTIFY_BOT_URL)")
        return
    url = f"{NOTIFY_BOT_URL.rstrip('/')}/notify"
    headers = {"X-Notify-Token": NOTIFY_AUTH_TOKEN} if NOTIFY_AUTH_TOKEN else {}
    payload = {"chat_id": int(chat_id), "text": text}

    sess = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=(502, 503, 504))
    sess.mount("http://", HTTPAdapter(max_retries=retries))
    sess.mount("https://", HTTPAdapter(max_retries=retries))

    try:
        # timeout=(connect, read)
        r = sess.post(url, json=payload, headers=headers, timeout=(2, 5))
        r.raise_for_status()
        app.logger.info("notify: delivered to chat_id=%s", chat_id)
    except Exception:
        app.logger.warning("notify: failed to deliver to chat_id=%s", chat_id, exc_info=True)

def _notify_text_via_notify_bot(chat_id: int, text: str) -> None:
    """Залишаємо СТАРЕ ім'я, але тепер це просто thin-wrapper на _notify__post."""
    _notify__post(chat_id, text)

def _notify_async_text(chat_id: int, text: str) -> None:
    """Неблокуючий запуск у фоні."""
    try:
        Thread(target=_notify__post, args=(chat_id, text), daemon=True).start()
    except Exception:
        # На крайній випадок — синхронний фолбек
        app.logger.warning("notify: thread spawn failed, falling back to sync", exc_info=True)
        _notify__post(chat_id, text)
# ======================================================================
# ------------------- auth -------------------
@app.post("/api/auth")
def auth():
    js = request.get_json(silent=True) or {}
    nickname = js.get("nickname") or js.get("user") or request.form.get("nickname") or request.form.get("user")
    code = js.get("code") or request.form.get("code")
    if not nickname or not code:
        abort(400, "nickname and code required")
    with _session() as db:
        u = _user_by_nickname(db, nickname)
        if not u or str(getattr(u, "code", "")) != str(code):
            abort(401, "invalid credentials")
        token = secrets.token_urlsafe(24)
        try:
            s = S(user_id=u.id, token=token, created_at=dt.utcnow())
            db.add(s)
            db.commit()
        except Exception:
            db.rollback()
        return jsonify(ok=True, user_key=u.user_key, nickname=u.nickname, session=token)

# ------------------- upload -------------------
@app.post("/api/upload")
def upload():
    user_key = request.args.get("user_key") or request.form.get("user_key")
    target = (request.args.get("target") or request.form.get("target") or "").strip() or "tg"
    source = (request.args.get("source") or request.form.get("source") or "").strip() or "ui"
    if request.path.endswith("/bot_upload"):
        source = "telegram"
    f = request.files.get("file")
    if not user_key or not f:
        abort(400, "user_key and file are required")

    with _session() as db:
        u = _user_by_key(db, user_key)
        filename = secure_filename(f.filename or f"upload-{uuid.uuid4().hex}")
        mime = f.mimetype or mimetypes.guess_type(filename)[0] or "video/webm"
        ext = os.path.splitext(filename)[1] or _ext_from_mime(mime)
        vid_name = f"{dt.utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex}{ext}"
        dst = _safe_join(REVIEW_DIR, vid_name)
        f.save(dst)
        v = Video(
            user_id=u.id,
            path=dst,
            status="review",
            target=target,
            source=source,
            mime=mime,
            created_at=dt.utcnow(),
        )
        db.add(v)
        db.commit()

        try:
            nick = getattr(u, "nickname", "user")
            direction = "TG → review" if source == "telegram" else "UI → review"
            text = f"{nick} {direction}"
            if NOTIFY_CHAT_ID:
                _notify_async_text(int(NOTIFY_CHAT_ID), text)
            elif getattr(u, "tg_chat_id", None):
                _notify_async_text(int(u.tg_chat_id), text)
        except Exception:
            app.logger.warning("review notify text failed", exc_info=True)

        return jsonify(ok=True, id=v.id)

# alias для бота
@app.post("/api/bot_upload")
def bot_upload():
    return upload()

# ------------------- lists -------------------
def _video_json(u: User, v: Video):
    return {
        "id": v.id,
        "user_id": getattr(v, "user_id", None),
        "status": getattr(v, "status", None),
        "source": getattr(v, "source", None),
        # було: "target": getattr(v, "target", None),
        # стало: "inbox" віддаємо як "ui", щоб адмінка бачила правильно
        "target": ("ui" if (getattr(v, "target", None) or "") == "inbox" else getattr(v, "target", None)),
        "mime": getattr(v, "mime", None),
        "created_at": (v.created_at.isoformat() if getattr(v, "created_at", None) else None),
        "playback_url": _public_file_url(v.id, getattr(u, "user_key", None)),
        "path": getattr(v, "path", None),
    }

@app.get("/api/review")
def list_review():
    user_key = request.args.get("user_key")
    limit = request.args.get("limit", type=int)
    with _session() as db:
        u = _user_by_key(db, user_key)
        q = db.query(Video).where(Video.user_id == u.id, Video.status == "review").order_by(Video.created_at.desc())
        rows = q.all()
        if limit:
            rows = rows[:limit]
        return jsonify(items=[_video_json(u, v) for v in rows])

@app.get("/api/inbox")
def list_inbox():
    user_key = request.args.get("user_key")
    limit = request.args.get("limit", type=int)
    with _session() as db:
        u = _user_by_key(db, user_key)
        q = db.query(Video).where(
            Video.user_id == u.id,
            Video.status == "published",
            Video.target == "inbox",
        ).order_by(Video.created_at.desc())
        rows = q.all()
        if limit:
            rows = rows[:limit]
        return jsonify(items=[_video_json(u, v) for v in rows])

@app.get("/api/published")
def list_published():
    user_key = request.args.get("user_key")
    target = request.args.get("target")
    limit = request.args.get("limit", type=int)
    with _session() as db:
        u = _user_by_key(db, user_key)
        # 🔧 НОВЕ: якщо клієнт просить target=ui, шукаємо 'inbox'
        if target == "ui":
            target = "inbox"
        q = db.query(Video).where(Video.user_id == u.id, Video.status == "published")
        if target:
            q = q.filter(Video.target == target)
        q = q.order_by(Video.created_at.desc())
        rows = q.all()
        if limit:
            rows = rows[:limit]
        return jsonify(items=[_video_json(u, v) for v in rows])


# ------------------- serve file -------------------
@app.get("/api/u/file/<int:video_id>")
def serve_file(video_id: int):
    user_key = request.args.get("user_key")
    with _session() as db:
        u = _user_by_key(db, user_key)
        v = db.get(Video, video_id)
        if not v:
            abort(404)
        if v.user_id != u.id:
            abort(403)
        path = getattr(v, "path", None)
        if not path or not os.path.exists(path):
            abort(404)
        mime = getattr(v, "mime", None) or mimetypes.guess_type(path)[0] or "application/octet-stream"
        return send_file(path, mimetype=mime, as_attachment=False, conditional=True)

# ------------------- bot link chat -------------------
@app.post("/api/tg/link_chat")
def tg_link_chat():
    js = request.get_json(force=True, silent=True) or {}
    user_key = js.get("user_key")
    chat_id = js.get("chat_id")
    if not user_key or not chat_id:
        abort(400, "user_key and chat_id required")
    with _session() as db:
        u = _user_by_key(db, user_key)
        u.tg_chat_id = int(chat_id)
        db.commit()
        return jsonify(ok=True)

# ------------------- admin users -------------------
@app.route("/api/admin/users", methods=["GET", "POST"])
@require_admin
def admin_users():
    if request.method == "GET":
        with _session() as db:
            rows = db.execute(select(User).order_by(User.id.asc())).scalars().all()
            items = [{
                "id": u.id,
                "nickname": getattr(u, "nickname", None),
                "user_key": getattr(u, "user_key", None),
                "role": getattr(u, "role", None),
                "enabled": getattr(u, "enabled", True),
                "tg_chat_id": getattr(u, "tg_chat_id", None),
                "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else None,
            } for u in rows]
            return jsonify(items=items)

    js = request.get_json(silent=True) or {}
    nickname = (js.get("nickname") or request.form.get("nickname") or "").strip()
    code = str(js.get("code") or request.form.get("code") or "").strip()
    role = (js.get("role") or request.form.get("role") or "user").strip()
    enabled = (js.get("enabled") if "enabled" in js else request.form.get("enabled"))
    enabled = bool(enabled) if enabled is not None else True

    if not nickname or not code:
        abort(400, "nickname and code required")

    with _session() as db:
        existed = db.execute(select(User).where(User.nickname == nickname)).scalars().first()
        if existed:
            abort(409, "nickname already exists")
        user_key = js.get("user_key") or request.form.get("user_key") or secrets.token_hex(16)
        u = User(nickname=nickname, code=code, user_key=user_key, role=role,
                 enabled=enabled, created_at=dt.utcnow())
        db.add(u); db.commit()
        return jsonify(id=u.id, user_key=u.user_key), 201

# legacy alias expected by admin panel form
@app.post("/api/admin/user/create")
@require_admin
def admin_user_create_legacy():
    return admin_users()

@app.get("/api/admin/users/<int:user_id>")
@require_admin
def admin_user_get(user_id: int):
    with _session() as db:
        u = db.get(User, user_id)
        if not u:
            abort(404)
        return jsonify(
            id=u.id,
            nickname=u.nickname,
            user_key=u.user_key,
            role=u.role,
            enabled=bool(u.enabled),
            tg_chat_id=getattr(u, "tg_chat_id", None),
            created_at=u.created_at.isoformat() if u.created_at else None,
        )

# update via PUT/POST (form-friendly)
@app.route("/api/admin/users/<int:user_id>", methods=["PUT", "POST"])
@require_admin
def admin_user_update(user_id: int):
    js = request.get_json(silent=True) or {}
    nickname = (js.get("nickname") or request.form.get("nickname"))
    code = (js.get("code") or request.form.get("code"))
    role = (js.get("role") or request.form.get("role"))
    enabled_raw = js.get("enabled") if "enabled" in js else request.form.get("enabled")
    tg_chat_id_raw = js.get("tg_chat_id") if "tg_chat_id" in js else request.form.get("tg_chat_id")

    with _session() as db:
        u = db.get(User, user_id)
        if not u:
            abort(404)

        if nickname is not None:
            nickname = nickname.strip()
            if nickname != u.nickname:
                exists = db.execute(select(User).where(User.nickname == nickname)).scalars().first()
                if exists:
                    abort(409, "nickname already exists")
                u.nickname = nickname

        if code is not None:
            u.code = str(code).strip()

        if role is not None:
            u.role = role.strip()

        if enabled_raw is not None:
            u.enabled = bool(str(enabled_raw).lower() in ("1", "true", "on", "yes"))

        if tg_chat_id_raw is not None:
            u.tg_chat_id = int(tg_chat_id_raw) if str(tg_chat_id_raw).strip() else None

        db.commit()
        return jsonify(ok=True)

# delete REST
@app.delete("/api/admin/users/<int:user_id>")
@require_admin
def admin_delete_user(user_id: int):
    with _session() as db:
        u = db.get(User, user_id)
        if not u:
            abort(404)
        db.delete(u)
        db.commit()
        return jsonify(ok=True)

# legacy delete via POST (для форм)
@app.post("/api/admin/users/<int:user_id>/delete")
@require_admin
def admin_delete_user_post(user_id: int):
    return admin_delete_user(user_id)

# regen user_key (legacy кнопка в адмінці)
@app.post("/api/admin/users/<int:user_id>/regen")
@require_admin
def admin_user_regen(user_id: int):
    with _session() as db:
        u = db.get(User, user_id)
        if not u:
            abort(404)
        u.user_key = secrets.token_hex(16)
        db.commit()
        return jsonify(ok=True, user_key=u.user_key)

# alias для GET списку користувачів
@app.get("/api/users")
@require_admin
def list_users_alias():
    return admin_users()

# ------------------- admin videos -------------------
def _safe_unlink(p: str):
    try:
        if p and os.path.isfile(p):
            os.remove(p)
    except Exception:
        app.logger.exception("file remove failed: %s", p)

def _delete_video_record(db, v: Video):
    _safe_unlink(v.path or "")
    db.delete(v)
    db.commit()

@app.post("/api/approve")
@require_admin
def approve():
    js = request.get_json(silent=True) or {}
    vid = (
        js.get("id")
        or js.get("video_id")
        or request.args.get("id", type=int)
        or request.args.get("video_id", type=int)
        or request.form.get("id", type=int)
        or request.form.get("video_id", type=int)
    )
    target = (js.get("target") or request.args.get("target") or request.form.get("target") or "").strip()

    # 🔧 НОВЕ: мапимо 'ui' → 'inbox', приймаємо обидва варіанти
    if target == "ui":
        target = "inbox"

    if not vid or target not in ("tg", "inbox"):
        abort(400)

    with _session() as db:
        v = db.get(Video, vid)
        if not v:
            abort(404)
        v.status = "published"
        v.target = target
        v.published_at = dt.utcnow()
        _move_to_final_if_needed(v)
        db.commit()
        return jsonify(ok=True)


@app.delete("/api/admin/videos/<int:vid>")
@require_admin
def admin_delete_video_rest(vid: int):
    with _session() as db:
        v = db.get(Video, vid)
        if not v:
            abort(404, "video not found")
        _delete_video_record(db, v)
        return jsonify(ok=True, id=vid)

@app.post("/api/admin/videos/<int:vid>/delete")
@require_admin
def admin_delete_video_post(vid: int):
    return admin_delete_video_rest(vid)

@app.route("/api/admin/video/delete", methods=["POST", "DELETE"])
@require_admin
def admin_delete_video_legacy():
    vid = request.values.get("id", type=int)
    if not vid:
        abort(400, "id is required")
    return admin_delete_video_rest(vid)

@app.post("/api/reject")
@require_admin
def reject():
    js = request.get_json(silent=True) or {}
    vid = js.get("id") or request.args.get("id", type=int) or request.form.get("id", type=int)
    if not vid:
        abort(400, "id required")
    with _session() as db:
        v = db.get(Video, vid)
        if not v:
            abort(404)
        try:
            if getattr(v, "path", None) and os.path.exists(v.path):
                os.remove(v.path)
        except Exception:
            pass
        v.status = "deleted"
        db.commit()
        return jsonify(ok=True)

@app.get("/api/admin/videos")
@require_admin
def admin_videos():
    status = request.args.get("status")
    target = request.args.get("target")
    with _session() as db:
        q = db.query(Video).order_by(Video.created_at.desc())
        if status:
            q = q.filter(Video.status == status)
        if target:
            q = q.filter(Video.target == target)
        rows = q.all()
        def item(v: Video):
            return {
                "id": v.id,
                "owner_id": v.user_id,
                "status": v.status,
                "source": (v.source or "ui"),
                "target": v.target,
                "mime": v.mime,
                "path": v.path,
                "created_at": v.created_at.isoformat(),
                "published_at": v.published_at.isoformat() if getattr(v, "published_at", None) else None,
                "delivered_to_tg": bool(getattr(v, "delivered_to_tg", False)),
            }
        return jsonify(items=[item(v) for v in rows])

# ------------------- support -------------------
@app.get("/api/admin/support")
@require_admin
def admin_support_list():
    with _session() as db:
        rows = db.execute(select(SupportTicket).order_by(SupportTicket.created_at.desc())).scalars().all()
        items = []
        for t in rows:
            items.append({
                "id": t.id,
                "user_id": t.user_id,
                "user_key": t.user_key,
                "nickname": t.nickname,
                "message": t.message,
                "reply": t.reply,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "replied_at": t.replied_at.isoformat() if t.replied_at else None,
            })
        return jsonify(items=items)

@app.post("/api/support")
def support_create():
    js = request.get_json(silent=True) or {}
    user_key = js.get("user_key") or request.form.get("user_key")
    message = js.get("message") or request.form.get("message")
    if not user_key or not message:
        abort(400, "user_key and message required")
    with _session() as db:
        u = _user_by_key(db, user_key)
        t = SupportTicket(
            user_id=u.id, user_key=u.user_key, nickname=u.nickname,
            message=message, status="open", created_at=dt.utcnow(),
        )
        db.add(t)
        db.commit()
        if SUPPORT_BOT_URL:
            try:
                headers = {"X-Notify-Token": SUPPORT_NOTIFY_SECRET} if SUPPORT_NOTIFY_SECRET else {}
                requests.post(SUPPORT_BOT_URL, json={
                    "type": "support_new",
                    "ticket_id": t.id,
                    "nickname": u.nickname,
                    "message": message,
                }, headers=headers, timeout=6).raise_for_status()
            except Exception:
                app.logger.exception("support-bot notify failed")
        return jsonify(ok=True, id=t.id)

@app.get("/api/support")
def support_list_user():
    user_key = request.args.get("user_key")
    with _session() as db:
        u = _user_by_key(db, user_key)
        rows = db.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == u.id)
            .order_by(SupportTicket.created_at.desc())
        ).scalars().all()
        items = []
        for t in rows:
            items.append({
                "id": t.id,
                "message": t.message,
                "reply": t.reply,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "replied_at": t.replied_at.isoformat() if t.replied_at else None,
            })
        return jsonify(items=items)

@app.post("/api/admin/support/<int:ticket_id>/reply")
@require_admin
def support_reply(ticket_id: int):
    js = request.get_json(silent=True) or {}
    reply = js.get("reply") or request.form.get("reply")
    if not reply:
        abort(400, "reply required")
    with _session() as db:
        t = db.get(SupportTicket, ticket_id)
        if not t:
            abort(404)
        t.reply = reply
        t.status = "answered"
        t.replied_at = dt.utcnow()
        db.commit()
        if SUPPORT_BOT_URL:
            try:
                headers = {"X-Notify-Token": SUPPORT_NOTIFY_SECRET} if SUPPORT_NOTIFY_SECRET else {}
                requests.post(SUPPORT_BOT_URL, json={
                    "type": "support_reply",
                    "ticket_id": t.id,
                    "user_key": t.user_key,
                    "nickname": t.nickname,
                    "reply": t.reply,
                }, headers=headers, timeout=6).raise_for_status()
            except Exception:
                app.logger.exception("support-bot notify failed")
        return jsonify(ok=True)

# UI aliases
@app.get("/api/user/sent")
def user_sent_alias():
    return list_review()

@app.get("/api/user/inbox")
def user_inbox_alias():
    return list_inbox()

# ======= ADMIN COMPAT SHIMS (повна сумісність зі старими маршрутами) =======
# 1) create (адмінка інколи шле POST на /api/admin/user/create або /api/admin/users/create)
@app.route("/api/admin/user/create", methods=["GET", "POST"])
@app.route("/api/admin/users/create", methods=["GET", "POST"])
@require_admin
def admin_user_create_compat():
    if request.method == "GET":
        return _forward_to("/api/admin/users", "GET")
    payload = _get_payload()
    if isinstance(payload, ImmutableMultiDict):
        payload = payload.to_dict(flat=True)
    if "enabled" in payload:
        v = str(payload["enabled"]).lower()
        payload["enabled"] = v in ("1", "true", "on", "yes")
    return _forward_to("/api/admin/users", "POST", payload)

# 2) GET один користувач
@app.route("/api/admin/user/<int:user_id>", methods=["GET"])
@require_admin
def admin_user_get_compat(user_id: int):
    return _forward_to(f"/api/admin/users/{user_id}", "GET")

# 3) update/save (POST/PUT)
@app.route("/api/admin/user/<int:user_id>/update", methods=["POST", "PUT"])
@app.route("/api/admin/user/<int:user_id>/save", methods=["POST", "PUT"])
@require_admin
def admin_user_update_compat(user_id: int):
    payload = _get_payload()
    if isinstance(payload, ImmutableMultiDict):
        payload = payload.to_dict(flat=True)
    if "enabled" in payload:
        v = str(payload["enabled"]).lower()
        payload["enabled"] = v in ("1", "true", "on", "yes")
    return _forward_to(f"/api/admin/users/{user_id}", request.method, payload)

# 4) regen key
@app.route("/api/admin/user/<int:user_id>/regen", methods=["POST"])
@require_admin
def admin_user_regen_compat(user_id: int):
    return _forward_to(f"/api/admin/users/{user_id}/regen", "POST")

# 5) delete (POST або DELETE)
@app.route("/api/admin/user/<int:user_id>/delete", methods=["POST", "DELETE"])
@require_admin
def admin_user_delete_compat(user_id: int):
    resp = _forward_to(f"/api/admin/users/{user_id}/delete", "POST")
    if resp.status_code in (404, 405):
        resp = _forward_to(f"/api/admin/users/{user_id}", "DELETE")
    return resp

# 6) список (GET)
@app.route("/api/admin/user/list", methods=["GET"])
@require_admin
def admin_user_list_compat():
    return _forward_to("/api/admin/users", "GET")
# ======= END ADMIN COMPAT SHIMS =======

# --------- Додаткові сумісні редіректи (на випадок старих шляхів) ----------
@app.route("/api/users", methods=["GET", "POST"])
def compat_users_root():
    return redirect("/api/admin/users", code=307)

@app.route("/api/users/create", methods=["GET", "POST"])
def compat_users_create():
    return redirect("/api/admin/users", code=307)

@app.route("/api/user/create", methods=["GET", "POST"])
def compat_user_create_singular():
    return redirect("/api/admin/user/create", code=307)

@app.route("/api/users/<int:user_id>", methods=["GET", "POST", "PUT", "DELETE"])
def compat_user_detail(user_id: int):
    return redirect(f"/api/admin/users/{user_id}", code=307)

@app.route("/api/user/<int:user_id>", methods=["GET", "POST", "PUT", "DELETE"])
def compat_user_detail_singular(user_id: int):
    return redirect(f"/api/admin/user/{user_id}", code=307)

@app.route("/api/users/<int:user_id>/delete", methods=["GET", "POST", "DELETE"])
def compat_user_delete(user_id: int):
    return redirect(f"/api/admin/users/{user_id}/delete", code=307)

@app.route("/api/user/<int:user_id>/delete", methods=["GET", "POST", "DELETE"])
def compat_user_delete_singular(user_id: int):
    return redirect(f"/api/admin/user/{user_id}/delete", code=307)

@app.route("/api/users/<int:user_id>/regen", methods=["GET", "POST"])
def compat_user_regen(user_id: int):
    return redirect(f"/api/admin/users/{user_id}/regen", code=307)

@app.route("/api/user/<int:user_id>/regen", methods=["GET", "POST"])
def compat_user_regen_singular(user_id: int):
    return redirect(f"/api/admin/user/{user_id}/regen", code=307)
# ---------------------------------------------------------------------------
@app.delete("/api/v1/admin/support/<int:ticket_id>")  #--------support_delete_ticket-----------
@require_admin
def _v1_support_delete(ticket_id: int):
    sess = SessionLocal()
    try:
        t = sess.get(SupportTicket, ticket_id)
        if not t:
            return jsonify({"deleted": False, "reason":"not_found"}), 404
        sess.delete(t)
        sess.commit()
        return jsonify({"deleted": True})
    finally:
        sess.close()
# ------------------- main -------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

