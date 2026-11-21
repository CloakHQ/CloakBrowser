#!/usr/bin/env bash
set -euo pipefail

cloakserve --idle-timeout="${CLOAKSERVE_IDLE_TIMEOUT:-300}" &
cloakserve_pid=$!
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
caddy_pid=$!

cleanup() {
	kill "$cloakserve_pid" "$caddy_pid" 2>/dev/null || true
	wait "$cloakserve_pid" "$caddy_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM

set +e
wait -n "$cloakserve_pid" "$caddy_pid"
status=$?
set -e
exit "$status"