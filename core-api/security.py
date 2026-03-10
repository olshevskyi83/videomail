import os
from functools import wraps
from flask import request, abort

ADMIN_BEARER_TOKEN = os.getenv("ADMIN_BEARER_TOKEN", "change-me")

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            abort(401)
        token = auth.split(" ", 1)[1].strip()
        if token != ADMIN_BEARER_TOKEN:
            abort(401)
        return fn(*args, **kwargs)
    return wrapper
