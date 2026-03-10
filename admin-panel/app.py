# app.py — admin-panel (повна версія, готова до копі-пасти)

import os
from flask import Flask, request, redirect, render_template, render_template_string, url_for, abort, flash
import requests

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET", "devsecret")

# --------- конфіг ---------
CORE_API = os.getenv("CORE_API_URL", "http://core-api:8000").rstrip("/")
ADMIN_BEARER_TOKEN = os.getenv("ADMIN_BEARER_TOKEN", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme_admin")
BASE_DIR = os.getenv("BASE_DIR", "")

# --------- утиліти ---------
def _api(path: str) -> str:
    p = path if path.startswith("/api/") else f"/api/{path.lstrip('/')}"
    return f"{CORE_API}{p}"

def _adm_headers():
    if not ADMIN_BEARER_TOKEN:
        abort(500, "ADMIN_BEARER_TOKEN not set")
    return {"Authorization": f"Bearer {ADMIN_BEARER_TOKEN}"}

def _request(method: str, path: str, *, params=None, json=None, allow_404_405=False):
    url = _api(path)
    r = requests.request(method, url, params=params, json=json, headers=_adm_headers(), timeout=20)
    if allow_404_405 and r.status_code in (404, 405):
        # дозвіл для каскадних спроб
        return r
    r.raise_for_status()
    return r

def _get(path, **params):
    return _request("GET", path, params=params).json()

def _post(path, payload):
    return _request("POST", path, json=payload).json()

def _delete(path, **params):
    return _request("DELETE", path, params=params).json()

def _guard():
    if request.cookies.get("adm_auth") != "1":
        return redirect(url_for("login", next=request.full_path or "/"))

def _dir_label(item: dict) -> str:
    """Формуємо підпис напрямку як 'ui → tg' або 'tg → ui'."""
    src = (item.get("source") or "ui").lower()
    if src == "telegram":
        src = "tg"
    tgt = (item.get("target") or ("inbox" if src in ("tg", "telegram") else "tg")).lower()
    return f"{src} \u2192 {tgt}"

# --------- обгортки з fallback для нестабільних роутів ядра ---------
def core_approve_video(video_id: int, target: str):
    """Спочатку намагаємось єдиний POST /api/approve; якщо його нема, падаємо на старі варіанти."""
    payload = {"id": video_id, "video_id": video_id, "target": target}
    r = _request("POST", "approve", json=payload, allow_404_405=True)
    if r.status_code not in (404, 405):
        r.raise_for_status()
        return r.json()

    # Спроба старого стилю: /api/admin/videos/{id}/approve?target=...
    r2 = _request("POST", f"admin/videos/{video_id}/approve", params={"target": target}, allow_404_405=True)
    if r2.status_code in (404, 405):
        abort(404, f"Approve endpoint not found in core-api (tried /api/approve and /api/admin/videos/{video_id}/approve)")
    r2.raise_for_status()
    return r2.json()

def core_delete_video(video_id: int):
    """Каскадно пробуємо всі популярні схеми видалення, поки одне не спрацює."""
    tries = [
        ("DELETE", f"admin/videos/{video_id}", None, None),                 # DELETE /api/admin/videos/{id}
        ("POST",   f"admin/videos/{video_id}/delete", None, {}),            # POST /api/admin/videos/{id}/delete
        ("DELETE", "admin/video", {"id": video_id}, None),                  # DELETE /api/admin/video?id={id}
        ("POST",   "admin/video/delete", None, {"id": video_id}),           # POST /api/admin/video/delete {id}
    ]
    last_resp = None
    for method, path, params, json in tries:
        resp = _request(method, path, params=params, json=json, allow_404_405=True)
        last_resp = resp
        if resp.status_code not in (404, 405):
            resp.raise_for_status()
            return resp.json()
    # якщо сюди дійшли — все погано
    text = last_resp.text if last_resp is not None else "no response"
    abort(404, f"Delete endpoint not found in core-api (tried several). Last response: {text}")

# ---------- auth ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            resp = redirect(request.args.get("next") or url_for("home"))
            resp.set_cookie("adm_auth", "1", httponly=True, samesite="Lax")
            return resp
        return render_template("login.html", error="Невірний пароль")
    return render_template("login.html")

@app.get("/logout")
def logout():
    resp = redirect(url_for("login"))
    resp.delete_cookie("adm_auth")
    return resp

# ---------- dashboard summary ----------
def _pull_user_list(user_key: str, name: str):
    r = _request("GET", name, params={"user_key": user_key})
    r.raise_for_status()
    return r.json().get("items", [])

def _load_user_summary():
    users = _get("users").get("items", [])
    items = []
    for u in users:
        uk = u.get("user_key")
        to_review = len(_pull_user_list(uk, "review")) if uk else 0
        published = _pull_user_list(uk, "published") if uk else []
        pu = sum(1 for it in published if (it.get("target") or "ui") == "ui")
        pt = sum(1 for it in published if it.get("target") == "tg")

        items.append({
            "id": u.get("id"),
            "nickname": u.get("nickname"),
            "name": u.get("name") or "",
            "user_key": uk,
            "to_review": to_review,
            "published_ui": pu,
            "published_tg": pt,
            "last_video_at": None,
        })
    items.sort(key=lambda x: (-x["to_review"], (x["nickname"] or "")))
    return items

@app.get("/")
def home():
    g = _guard()
    if g: return g
    summary = _load_user_summary()
    return render_template("index.html", summary=summary, base_dir=BASE_DIR)

# ---------- users ----------
@app.get("/users")
def users():
    g = _guard()
    if g: return g
    data = _get("users")
    return render_template("users.html", users=data.get("items", []), base_dir=BASE_DIR)

@app.post("/users/create")
def users_create():
    g = _guard();  g and (_ for _ in ()).throw(StopIteration)
    payload = {
        "nickname": (request.form.get("nickname") or "").strip(),
        "code":     (request.form.get("code") or "").strip(),
        "role":     (request.form.get("role") or "user").strip(),
        "enabled":  True if request.form.get("enabled") == "on" else False,
    }
    if not payload["nickname"]:
        flash("Нікнейм обов'язковий", "err")
        return redirect(url_for("users"))
    try:
        _post("users", payload)
        flash("Користувача створено", "ok")
    except requests.HTTPError as e:
        flash(f"Помилка створення: {e.response.text}", "err")
    return redirect(url_for("users"))

@app.post("/users/<int:uid>/delete")
def users_delete(uid: int):
    g = _guard();  g and (_ for _ in ()).throw(StopIteration)
    try:
        _delete(f"users/{uid}")
        flash("Користувача видалено", "ok")
    except requests.HTTPError as e:
        flash(f"Помилка видалення: {e.response.text}", "err")
    return redirect(url_for("users"))

@app.post("/users/<int:uid>/regen")
def users_regen(uid: int):
    g = _guard();  g and (_ for _ in ()).throw(StopIteration)
    try:
        _post(f"users/{uid}/regenerate_key", {})
        flash("Ключ згенеровано заново", "ok")
    except requests.HTTPError as e:
        flash(f"Помилка: {e.response.text}", "err")
    return redirect(url_for("users"))

# ---------- videos по юзеру ----------
def _map_with_preview(items, user_key):
    out = []
    for it in items or []:
        vid = it.get("id")
        out.append({
            "id": vid,
            "created_at": it.get("created_at"),
            "source": it.get("source"),
            "target": it.get("target"),
            "preview_url": f"/api/u/file/{vid}?user_key={user_key}",
            "dir_label": _dir_label(it),
        })
    return out

@app.get("/videos/<user_key>")
def videos(user_key: str):
    g = _guard()
    if g: return g
    review = _map_with_preview(_pull_user_list(user_key,"review"), user_key)
    published = _map_with_preview(_pull_user_list(user_key,"published"), user_key)
    published_ui = [x for x in published if (x.get("target") or "ui") == "ui"]
    published_tg = [x for x in published if x.get("target") == "tg"]

    return render_template("videos.html",
                           user_key=user_key,
                           review=review,
                           published_ui=published_ui,
                           published_tg=published_tg)

# ---------- review (глобальний) ----------
@app.get("/review")
def review_all():
    g = _guard()
    if g: return g
    data = _get("admin/videos", status="review")
    items = data.get("items", [])

    rows = []
    for it in items:
        vid = it.get("id")
        mime = it.get("mime") or ""
        created = (it.get("created_at") or "").replace("T"," ")[:19]
        badge = _dir_label(it)
        rows.append(f"""
          <li style="margin:8px 0;padding:8px;border:1px solid #e5e7eb;border-radius:10px">
            <span style="display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #c7d2fe;background:#eef2ff;color:#1e3a8a;font-weight:700;font-size:12px">{badge}</span>
            <b style="margin-left:8px">#{vid}</b>
            <span style="color:#6b7280;margin-left:8px">{mime}</span>
            <span style="color:#9aa1ad;margin-left:8px">{created}</span>

            <form method="post" action="/videos/approve_tg" style="display:inline;margin-left:12px">
              <input type="hidden" name="video_id" value="{vid}">
              <button>Approve to TG</button>
            </form>

            <form method="post" action="/videos/approve_inbox" style="display:inline;margin-left:6px">
              <input type="hidden" name="video_id" value="{vid}">
              <button>Approve to Inbox</button>
            </form>

            <form method="post" action="/videos/delete" style="display:inline;margin-left:6px">
              <input type="hidden" name="video_id" value="{vid}">
              <button style="color:#b91c1c">Delete</button>
            </form>
          </li>
        """)

    html = f"""
    <!doctype html>
    <html lang="uk">
    <head><meta charset="utf-8"><title>Review</title>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu; padding: 14px; }}
      a {{ color: #2563eb; text-decoration: none; }}
      .nav a {{ margin-right: 12px; }}
    </style>
    </head>
    <body>
      <div class="nav">
        <a href="/">Dashboard</a>
        <a href="/users">Users</a>
        <a href="/review"><b>Review</b></a>
        <a href="/support">Support</a>
        <a href="/logout" style="float:right">Вийти</a>
      </div>
      <h2>Review</h2>
      <ul style="list-style:none;padding-left:0">
        {''.join(rows) or '<li>Порожньо</li>'}
      </ul>
    </body></html>
    """
    return html

# ---------- дії з відео ----------
@app.post("/videos/approve_inbox")
def v_approve_inbox():
    g = _guard();  g and (_ for _ in ()).throw(StopIteration)
    vid = int(request.form.get("video_id") or request.form.get("id") or 0)
    if not vid: abort(400)
    core_approve_video(vid, "inbox")
    return redirect(request.referrer or url_for("review_all"))

@app.post("/videos/approve_tg")
def v_approve_tg():
    g = _guard();  g and (_ for _ in ()).throw(StopIteration)
    vid = int(request.form.get("video_id") or request.form.get("id") or 0)
    if not vid: abort(400)
    core_approve_video(vid, "tg")
    return redirect(request.referrer or url_for("review_all"))

@app.post("/videos/delete")
def v_delete():
    g = _guard();  g and (_ for _ in ()).throw(StopIteration)
    vid = int(request.form.get("video_id") or request.form.get("id") or 0)
    if not vid: abort(400)
    core_delete_video(vid)
    return redirect(request.referrer or url_for("review_all"))

# ---------- support ----------
@app.get("/support")
def support_list():
    g = _guard()
    if g: return g
    # базовий сучасний шлях
    r = _request("GET", "admin/support", allow_404_405=True)
    if r.status_code in (404, 405):
        # старий варіант на всяк випадок
        r = _request("GET", "support/admin")
    items = r.json().get("items", [])
    return render_template("support.html", items=items)

@app.post("/support/reply")
def support_reply():
    g = _guard();  g and (_ for _ in ()).throw(StopIteration)
    tid = request.form.get("id", type=int)
    text = (request.form.get("reply") or "").strip()
    if not tid or not text:
        flash("Порожня відповідь або неправильний id", "err")
        return redirect(url_for("support_list"))
    # сучасний шлях
    r = _request("POST", f"admin/support/{tid}/reply", json={"reply": text}, allow_404_405=True)
    if r.status_code in (404, 405):
        # fallback старий
        r = _request("POST", "support/reply", json={"id": tid, "reply": text})
    try:
        r.raise_for_status()
        flash("Відповідь надіслана", "ok")
    except requests.HTTPError as e:
        flash(f"Помилка відправлення: {e.response.text}", "err")
    return redirect(url_for("support_list"))

@app.post("/support/<int:ticket_id>/delete")
def support_delete(ticket_id: int):
    g = _guard()
    if g: return g

    def try_call(method, path, *, params=None, json=None):
        try:
            r = _request(method, path, params=params, json=json, allow_404_405=True)
            if r.status_code in (404, 405):
                return None
            r.raise_for_status()
            return r
        except Exception:
            return None

    # 1) legacy admin JSON (якщо у тебе колись був такий шлях)
    resp = try_call("POST", f"admin/support/{ticket_id}/delete", json={"id": ticket_id})
    if not resp:
        # 2) legacy generic JSON (ще давніший випадок)
        resp = try_call("POST", "support/delete", json={"id": ticket_id})
    if not resp:
        # 3) v1 правильний шлях (твій бекенд його має)
        resp = try_call("DELETE", f"v1/admin/support/{ticket_id}")

    if not resp:
        flash("Не вдалося видалити: жоден endpoint не прийняв запит", "err")
        return redirect(url_for("support_list"))

    try:
        js = resp.json()
    except Exception:
        js = {}
    if isinstance(js, dict) and js.get("deleted") is True:
        flash(f"Розмову #{ticket_id} видалено", "ok")
    elif 200 <= resp.status_code < 300:
        flash(f"Розмову #{ticket_id} видалено", "ok")
    else:
        flash(f"Не вдалося видалити (код {resp.status_code})", "err")
    return redirect(url_for("support_list"))



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

