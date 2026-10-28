#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./scripts/install-utils.sh
install_init "$PWD" "Creature Lab"
install_enable_traps

action="run"
case "${1:-}" in run|doctor|repair|docker|stop|logs) action=$1; shift ;; esac
no_browser=0
forward=()
for arg in "$@"; do
  [ "$arg" = "--no-browser" ] && { no_browser=1; continue; }
  forward+=("$arg")
done
uv_version="0.12.5"

find_uv() {
  command -v uv 2>/dev/null || {
    [ -x "$HOME/.local/bin/uv" ] && { printf '%s\n' "$HOME/.local/bin/uv"; return; }
    [ -x "$HOME/.cargo/bin/uv" ] && { printf '%s\n' "$HOME/.cargo/bin/uv"; return; }
    return 1
  }
}
install_uv() {
  local file; file=$(mktemp)
  install_download "https://astral.sh/uv/${uv_version}/install.sh" "$file" "uv download"
  sh "$file"; rm -f "$file"; find_uv
}
wait_ready() {
  for _ in $(seq 1 120); do
    if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 http://127.0.0.1:8080 >/dev/null 2>&1; then return; fi
    if command -v wget >/dev/null 2>&1 && wget -qO- --timeout=2 http://127.0.0.1:8080 >/dev/null 2>&1; then return; fi
    sleep 0.5
  done
  return 1
}

case "$action" in
  docker|stop|logs)
    if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
      [ "$action" = stop ] && { echo "The native server runs in the foreground. Press Ctrl+C in its terminal to stop it."; exit 0; }
      [ "$action" = logs ] && { echo "The native server writes logs to its foreground terminal."; exit 0; }
      command -v docker >/dev/null 2>&1 || { echo "Docker is not installed." >&2; exit 1; }
      echo "Docker is installed but its engine is not running." >&2
      exit 1
    fi
    [ "$action" = stop ] && exec docker compose down
    [ "$action" = logs ] && exec docker compose logs --follow
    install_lock
    install_require_space "$PWD" 3
    docker compose up --detach --build
    wait_ready || { docker compose logs; echo "Creature Lab did not become ready." >&2; exit 1; }
    install_complete
    echo "Creature Lab is ready at http://127.0.0.1:8080"
    if [ "$no_browser" -eq 0 ]; then
      command -v open >/dev/null 2>&1 && open http://127.0.0.1:8080 || command -v xdg-open >/dev/null 2>&1 && xdg-open http://127.0.0.1:8080 || true
    fi
    exit 0 ;;
esac

uv=$(find_uv || true)
if [ "$action" = doctor ]; then
  [ -n "$uv" ] || { echo "uv is missing. Run ./run.sh once." >&2; exit 1; }
  exec "$uv" run --frozen --no-sync creature-lab doctor
fi
install_lock
install_require_space "$PWD" 3
[ -n "$uv" ] || uv=$(install_uv)
sync_args=(sync --frozen --extra sim --extra viz)
[ "$action" = repair ] && sync_args+=(--reinstall)
install_retry "dependency synchronization" "$uv" "${sync_args[@]}"
install_complete

args=(run --frozen --no-sync python scripts/start.py --skip-sync)
[ "$no_browser" -eq 1 ] && args+=(--no-open-browser)
args+=("${forward[@]}")
exec "$uv" "${args[@]}"
