#!/usr/bin/env bash
set -euo pipefail

# ======================== Videomail Ops (Menu) =========================

PROJECT_DIR="${PROJECT_DIR:-/opt/videomail}"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_DIR/docker-compose.yml}"
SUDO="${SUDO:-sudo}"            # зроби SUDO="" якщо юзер у docker-групі
COMPOSE_BIN="${COMPOSE_BIN:-}"  # авто-визначиться
CORE_API_URL_DEFAULT="${CORE_API_URL_DEFAULT:-http://localhost:8000}"
ADMIN_BEARER_TOKEN="${ADMIN_BEARER_TOKEN:-}"
BASE_DIR="${BASE_DIR:-/srv/videomail}"

# Фіксований список залишаємо порожнім — зчитую з compose, щоб не ловити "no such service"
SERVICES_STATIC=()

color() { local c="$1"; shift; printf "\033[%sm%s\033[0m\n" "$c" "$*"; }
info()  { color "1;34" "ℹ $*"; }
ok()    { color "1;32" "✔ $*"; }
warn()  { color "1;33" "⚠ $*"; }
err()   { color "1;31" "✖ $*"; }
die()   { err "$*"; exit 1; }

banner() {
  echo
  color "1;36" "=== Videomail — керування стеком (docker compose) ==="
  echo "Проект : $PROJECT_DIR"
  echo "Compose: $COMPOSE_FILE"
  echo
}

detect_compose() {
  if [[ -n "$COMPOSE_BIN" ]]; then return 0; fi
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_BIN="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_BIN="docker-compose"
  else
    die "Не знайдено docker compose. Встанови Docker і compose plugin."
  fi
}

cd_project() {
  [[ -d "$PROJECT_DIR" ]] || die "Нема каталогу $PROJECT_DIR"
  cd "$PROJECT_DIR"
}

compose() {
  detect_compose
  cd_project
  # shellcheck disable=SC2086
  $SUDO $COMPOSE_BIN -f "$COMPOSE_FILE" "$@"
}

get_services() {
  if (( ${#SERVICES_STATIC[@]} )); then
    printf "%s\n" "${SERVICES_STATIC[@]}"
  else
    compose config --services | awk 'NF' | tr -d "\r"
  fi
}

pause() {
  echo
  read -rp "Натисни Enter, щоб продовжити..." _pause || true
}

need_token() {
  if [[ -z "$ADMIN_BEARER_TOKEN" ]]; then
    read -rsp "Введи ADMIN_BEARER_TOKEN: " ADMIN_BEARER_TOKEN
    echo
    [[ -n "$ADMIN_BEARER_TOKEN" ]] || die "Токен порожній."
  fi
}

# ---------- Фіксований вибір сервісу: меню в stderr, значення в stdout ----------
pick_service() {
  mapfile -t arr < <(get_services)
  (( ${#arr[@]} > 0 )) || die "Не знайшов жодного сервісу у compose."

  # Д друкуємо список у stderr, щоб не потрапив у підстановку
  {
    echo "Вибери сервіс:"
    local cols=2 width=0
    # порахуємо ширину для красивої сітки
    for s in "${arr[@]}"; do ((${#s} > width)) && width=${#s}; done
    local i=1
    for s in "${arr[@]}"; do
      printf " %2d) %-*s" "$i" "$width" "$s"
      if (( i % cols == 0 )); then printf "\n"; else printf "    "; fi
      ((i++))
    done
    # доб'ємо перенесення рядка, якщо непарна кількість
    (( (i-1) % cols == 1 )) && printf "\n"
    printf " %2d) %s\n" "$i" "Скасувати"
  } >&2

  local n
  read -rp "№: " n >&2
  if [[ ! "${n:-}" =~ ^[0-9]+$ ]]; then return 1; fi
  if (( n == i )); then return 1; fi
  if (( n < 1 || n > ${#arr[@]} )); then return 1; fi

  # Лише обрана назва — у stdout
  printf "%s" "${arr[$((n-1))]}"
}

# --------------------- Дії з контейнерами ----------------------
action_up()          { info "Підіймаю стек…"; compose up -d; ok "Готово."; }
action_down()        { info "Зупиняю стек…"; compose down; ok "Стек зупинено."; }
action_build_all()   { info "Білдую всі сервіси…"; compose build; ok "Білд завершено."; }
action_build_one()   { local s; s="$(pick_service)" || return 0; info "Білдую: $s"; compose build "$s"; ok "Готово."; }
action_restart_all() { info "Рестарт core-api, admin-panel, user-ui…"; compose restart core-api admin-panel user-ui || true; ok "Рестарт виконано."; }
action_restart_one() { local s; s="$(pick_service)" || return 0; info "Рестарт: $s"; compose restart "$s"; ok "Готово."; }
action_logs_all()    { info "Останні логи всіх…"; compose logs --tail=200; }
action_logs_follow() { local s; s="$(pick_service)" || return 0; info "Фолловлю логи: $s (Ctrl+C для виходу)"; compose logs -f "$s"; }
action_shell()       { local s; s="$(pick_service)" || return 0; info "Shell у $s…"; compose exec "$s" sh -lc 'bash || sh'; }
action_ports()       { info "Порти/стан контейнерів:"; compose ps; }
action_stats()       { info "Статистика контейнерів (разово):"; $SUDO docker stats --no-stream || true; }
action_prune()       { warn "docker system prune -af --volumes"; read -rp "Підтвердити? [y/N]: " a; [[ "${a,,}" == "y" ]] || { echo "Скасовано."; return; }; $SUDO docker system prune -af --volumes; ok "Прибрано."; }

# ------------------- Перевірки/health/smoke --------------------
curl_json_or_raw() {
  if command -v jq >/dev/null 2>&1; then
    curl -fsS "$1" | jq . || curl -fsS "$1"
  else
    curl -fsS "$1"
  fi
}

action_health() {
  echo "Підказка: з ХОСТА core-api як DNS-імʼя не резолвиться. Використовуй localhost:порт."
  read -rp "База URL core-api [$CORE_API_URL_DEFAULT]: " base
  base="${base:-$CORE_API_URL_DEFAULT}"
  info "Healthcheck @ $base"
  set +e
  curl_json_or_raw "$base/health"; echo
  curl_json_or_raw "$base/api/v1/ping"; echo
  set -e
  ok "Health запити виконані."
}

action_smoke() {
  echo "Підказка: з ХОСТА core-api як DNS-імʼя не резолвиться. Використовуй localhost:порт."
  read -rp "База URL core-api [$CORE_API_URL_DEFAULT]: " base
  base="${base:-$CORE_API_URL_DEFAULT}"
  if [[ -z "$ADMIN_BEARER_TOKEN" ]]; then
    read -rsp "Введи ADMIN_BEARER_TOKEN: " ADMIN_BEARER_TOKEN; echo
  fi
  local -a hdr=(-H "Authorization: Bearer $ADMIN_BEARER_TOKEN" -H "Content-Type: application/json")
  info "Smoke @ $base"
  set +e
  echo "== /health ==";                 curl_json_or_raw "$base/health"; echo
  echo "== /api/v1/ping ==";            curl_json_or_raw "$base/api/v1/ping"; echo
  echo "== users v1 ==";                curl -fsS "$base/api/v1/admin/users" "${hdr[@]}" | (command -v jq >/dev/null && jq . || cat); echo
  echo "== media inbox v1 ==";          curl -fsS "$base/api/v1/admin/media/inbox" "${hdr[@]}" | (command -v jq >/dev/null && jq . || cat); echo
  echo "== support v1 ==";              curl -fsS "$base/api/v1/admin/support" "${hdr[@]}" | (command -v jq >/dev/null && jq . || cat); echo
  echo "== legacy support (якщо є) =="; curl_json_or_raw "$base/api/support" || true; echo
  set -e
  ok "Smoke OK."
}

# ---------------------- Бекапи (файли) -------------------------
action_backup() {
  local dst_default="$PROJECT_DIR/backup_$(date +%F_%H%M%S).tar.gz"
  read -rp "Куди зберегти бекап [$dst_default]: " dst
  dst="${dst:-$dst_default}"
  info "Бекаплю $BASE_DIR → $dst"
  $SUDO tar -C "$(dirname "$BASE_DIR")" -czf "$dst" "$(basename "$BASE_DIR")"
  ok "Бекап збережено: $dst"
}

# --------------------------- Меню ------------------------------
main_menu() {
  while true; do
    banner
    cat <<'MENU'
 1) Up (підняти стек)
 2) Build ВСІ
 3) Build сервісу
 4) Restart критичних (core-api, admin-panel, user-ui)
 5) Restart сервісу
 6) Logs (останні всіх)
 7) Logs -f сервісу
 8) Shell у сервісі
 9) Ports/PS
10) Stats
11) Prune
12) Health
13) Smoke
14) Backup файлів
 0) Вихід
MENU
    echo
    read -rp "Вибір: " c
    case "${c:-}" in
      1) action_up ;;
      2) action_build_all ;;
      3) action_build_one ;;
      4) action_restart_all ;;
      5) action_restart_one ;;
      6) action_logs_all ;;
      7) action_logs_follow ;;
      8) action_shell ;;
      9) action_ports ;;
      10) action_stats ;;
      11) action_prune ;;
      12) action_health ;;
      13) action_smoke ;;
      14) action_backup ;;
      0) echo "Бувай."; exit 0 ;;
      *) err "Невірний вибір" ;;
    esac
    pause
  done
}

if [[ $# -gt 0 ]]; then
  warn "Скрипт працює в режимі меню. Запусти без аргументів: ./videomail.sh"
  exit 1
fi

main_menu
