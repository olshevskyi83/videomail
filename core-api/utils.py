from uuid import uuid4
from datetime import datetime, timedelta

def gen_user_key():
    return uuid4().hex

def gen_session_token():
    return uuid4().hex

def session_expiry(days: int = 7):
    return datetime.utcnow() + timedelta(days=days)
