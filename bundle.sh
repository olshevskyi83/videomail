#!/usr/bin/env bash
set -euo pipefail

ROOT="/opt/videomail"
TS="$(date +%Y-%m-%d_%H%M%S)"
OUTDIR="/tmp/videomail_bundle_${TS}"
DEST="${OUTDIR}/videomail_${TS}.tar.gz"

mkdir -p "${OUTDIR}/opt/videomail"

copy_safe() {
  src="$1"; dst="$2"
  if [ -f "${ROOT}/${src}" ]; then
    mkdir -p "$(dirname "${OUTDIR}/opt/videomail/${dst}")"
    cp -a "${ROOT}/${src}" "${OUTDIR}/opt/videomail/${dst}"
  fi
}

copy_dir_safe() {
  src="$1"; dst="$2"
  if [ -d "${ROOT}/${src}" ]; then
    mkdir -p "$(dirname "${OUTDIR}/opt/videomail/${dst}")"
    rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
      --exclude '.git' --exclude 'data/*' --exclude 'node_modules' \
      "${ROOT}/${src}/" "${OUTDIR}/opt/videomail/${dst}/"
  fi
}

# 1) core-api (код, конфіги — без медіа/БД)
copy_safe "core-api/app.py"              "core-api/app.py"
copy_safe "core-api/models.py"           "core-api/models.py"
copy_safe "core-api/db.py"               "core-api/db.py"
copy_safe "core-api/security.py"         "core-api/security.py"
copy_safe "core-api/utils.py"            "core-api/utils.py"
copy_safe "core-api/requirements.txt"    "core-api/requirements.txt"
copy_safe "core-api/gunicorn.conf.py"    "core-api/gunicorn.conf.py"
copy_safe "core-api/migrate_relatives.py" "core-api/migrate_relatives.py"
copy_safe "core-api/Dockerfile"          "core-api/Dockerfile"

# 2) admin-panel
copy_safe "admin-panel/app.py"           "admin-panel/app.py"
copy_safe "admin-panel/requirements.txt" "admin-panel/requirements.txt"
copy_dir_safe "admin-panel/templates"    "admin-panel/templates"
copy_safe "admin-panel/Dockerfile"       "admin-panel/Dockerfile"

# 3) user-ui
copy_safe "user-ui/ui.html"              "user-ui/ui.html"
copy_safe "user-ui/index.html"           "user-ui/index.html"
copy_safe "user-ui/app.js"               "user-ui/app.js"
copy_dir_safe "user-ui/config"           "user-ui/config"

# 4) bots
copy_safe "bots/family-bot/family_bot.py"       "bots/family-bot/family_bot.py"
copy_safe "bots/family-bot/requirements.txt"    "bots/family-bot/requirements.txt"
copy_safe "bots/family-bot/Dockerfile"          "bots/family-bot/Dockerfile"

copy_safe "bots/notify-bot/notify_bot.py"       "bots/notify-bot/notify_bot.py"
copy_safe "bots/notify-bot/requirements.txt"    "bots/notify-bot/requirements.txt"
copy_safe "bots/notify-bot/Dockerfile"          "bots/notify-bot/Dockerfile"

# 5) reverse-proxy
copy_safe "reverse-proxy/nginx.conf"     "reverse-proxy/nginx.conf"
copy_safe "reverse-proxy/Dockerfile"     "reverse-proxy/Dockerfile"

# 6) compose та конфіги
copy_safe "docker-compose.yml"           "docker-compose.yml"
copy_dir_safe "config"                   "config"

# 7) TLS — НЕ кладемо приватні ключі. Тільки info.txt зі списком файлів.
if [ -d "${ROOT}/tls" ]; then
  mkdir -p "${OUTDIR}/opt/videomail/tls"
  ls -1 "${ROOT}/tls" > "${OUTDIR}/opt/videomail/tls/_files_list.txt" || true
fi

# 8) Скрипти
copy_safe "videomail.sh"                 "videomail.sh"

#############################################
# Редакція секретів у скопійованих конфігах #
#############################################
redact() {
  f="$1"
  # Замінюємо значення змінних типу TOKEN/SECRET/PASSWORD/API_KEY
  sed -i -E \
    -e 's/([A-Za-z0-9_]*(TOKEN|SECRET|PASSWORD|API_KEY|WEBHOOK|BEARER|AUTH)[A-Za-z0-9_]*=).*/\1__REDACTED__/g' \
    -e 's#(telegramBotToken|bot_token|TELEGRAM_BOT_TOKEN)":[^"]*#\1":"__REDACTED__#g' \
    -e 's#("NOTIFY_AUTH_TOKEN"\s*:\s*")[^"]*#\1__REDACTED__#g' \
    -e 's#(NOTIFY_AUTH_TOKEN":\s*")[^"]*#\1__REDACTED__#g' \
    "${f}" || true
}

# Пробігаємося по всіх потенційно чутливих файлах
find "${OUTDIR}/opt/videomail" -type f \( -name "*.env" -o -name "*.json" -o -name "*.yml" -o -name "*.yaml" -o -name "*.ini" -o -name "*.py" \) \
  | while read -r f; do
      # Не чіпаємо .crt/.pem/.key (ми їх і не копіювали)
      case "$f" in
        *.crt|*.pem|*.key) continue ;;
      esac
      redact "$f"
    done

# Контрольний список вмісту
( cd "${OUTDIR}"; tar -czf "${DEST}" opt )
sha256sum "${DEST}" > "${DEST}.sha256"

echo "Архів: ${DEST}"
echo "Хеш:   ${DEST}.sha256"
echo "Перевірити: sha256sum -c ${DEST}.sha256"
echo "Переглянути: tar -tzf ${DEST} | less"
