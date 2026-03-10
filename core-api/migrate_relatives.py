import os
import json
import argparse
from pathlib import Path
from db import db_session
from models import User, RoleEnum  # Base імпортовано в models і вже створює таблиці

REL_MAP_PATH = Path(os.getenv("REL_MAP_PATH", "/opt/videomail/config/relatives_map.json"))
SETTINGS_PATH = Path(os.getenv("SETTINGS_PATH", "/opt/videomail/config/settings.json"))


def load_relatives() -> dict[str, str]:
    rel = {}
    if REL_MAP_PATH.exists():
        data = json.loads(REL_MAP_PATH.read_text("utf-8"))
        users = data.get("users") if isinstance(data, dict) else data
        for nick, val in (users or {}).items():
            uk = val.get("user_key") if isinstance(val, dict) else str(val)
            if uk:
                rel[str(nick)] = uk
    return rel


def load_auth() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    settings = json.loads(SETTINGS_PATH.read_text("utf-8"))
    auth = settings.get("auth", {}) or {}
    return {str(k): str(v) for k, v in auth.items()}


def main(force_update_codes: bool = False) -> None:
    rel = load_relatives()
    auth = load_auth()

    with db_session() as s:
        # Кеш існуючих користувачів
        users_by_nick = {u.nickname: u for u in s.query(User).all()}
        users_by_key = {u.user_key: u for u in s.query(User).all() if u.user_key}

        for nick, user_key in rel.items():
            u_by_nick = users_by_nick.get(nick)
            u_by_key = users_by_key.get(user_key)

            if u_by_nick and u_by_key and u_by_nick.id != u_by_key.id:
                # Конфлікт: цей user_key уже прив’язаний до іншого користувача
                # Політика: ключ належить тому, хто в JSON (nick). Переносимо.
                if u_by_nick.user_key and u_by_nick.user_key != user_key:
                    # У nick вже є інший ключ → звільняти чужий ключ не будемо, пропустимо з попередженням
                    print(f"!! conflict: nickname {nick} already has different user_key={u_by_nick.user_key}, skip moving {user_key} from {u_by_key.nickname}")
                else:
                    print(f"-> reassign user_key {user_key} from {u_by_key.nickname} to {nick}")
                    u_by_key.user_key = None
                    u_by_nick.user_key = user_key
                    users_by_key[user_key] = u_by_nick  # оновлюємо кеш

            elif u_by_nick and not u_by_key:
                # Нік є, ключ вільний → присвоюємо якщо треба
                if not u_by_nick.user_key:
                    u_by_nick.user_key = user_key
                    users_by_key[user_key] = u_by_nick

            elif not u_by_nick and u_by_key:
                # Є юзер із цим ключем, але інше ім’я → перейменовувати НЕ будемо.
                # Якщо треба інше ім’я — адмін нехай править у /api/users. Просто створювати дубль не можна.
                print(f"!! mapping says {nick} -> {user_key}, but key already used by {u_by_key.nickname}. Skipping create.")

            else:
                # Нема ні ніку, ні ключа → створюємо нового
                u = User(
                    nickname=nick,
                    code=str(auth.get(nick) or ""),
                    role=RoleEnum.user,
                    enabled=True,
                    user_key=user_key,
                )
                s.add(u)
                s.flush()
                users_by_nick[nick] = u
                users_by_key[user_key] = u

        # Пройдемось по auth: додамо відсутніх або оновимо код (за прапорцем)
        for nick, code in auth.items():
            u = users_by_nick.get(nick)
            if not u:
                u = User(
                    nickname=nick,
                    code=str(code),
                    role=RoleEnum.user,
                    enabled=True,
                    user_key=rel.get(nick),
                )
                s.add(u)
                s.flush()
                users_by_nick[nick] = u
                if u.user_key:
                    users_by_key[u.user_key] = u
            else:
                if force_update_codes:
                    u.code = str(code)

    print(f"→ Migration complete (force_update_codes={force_update_codes})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force-update-codes", action="store_true")
    args = p.parse_args()
    main(force_update_codes=args.force_update_codes)
