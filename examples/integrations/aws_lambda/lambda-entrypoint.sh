#!/bin/sh
# Dual-mode entrypoint for the CloakBrowser Lambda image.
#
#   1. Always start Xvfb on :99 (same as the canonical bin/docker-entrypoint.sh)
#      so headed Chromium works no matter how the container is invoked.
#   2. Detect whether the CMD looks like a Lambda handler (a single
#      `module.func`-shaped argument). If yes, route through the Lambda runtime
#      client (using the bundled aws-lambda-rie locally, or talking to the real
#      Lambda Runtime API when AWS_LAMBDA_RUNTIME_API is set in production).
#   3. Otherwise exec the CMD directly — preserving the canonical Dockerfile's
#      interaction surface (`python`, `cloakserve`, `cloaktest`, `node`, `bash`,
#      `python examples/basic.py`, etc.).
set -e

mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# Clean any stale Xvfb state. If a previous Xvfb died and left its lock file
# behind (we observed this in cold-start storms), a new Xvfb refuses to start
# with "Server is already active for display 99". Removing both files makes
# Xvfb start cleanly every time.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/tmp/Xvfb.log 2>&1 &

# Wait for the X11 socket to appear AND for Xvfb to be ready to serve. The
# socket file appears at bind(), but listen() and the first accept() come
# slightly later — under cold-start CPU contention this gap matters.
i=0
while [ ! -e /tmp/.X11-unix/X99 ] && [ "$i" -lt 200 ]; do
    i=$((i + 1))
    sleep 0.05
done
# Small buffer after the socket appears so Xvfb has a moment to call listen()
# and start accepting clients. Cheap insurance against the bind/listen gap.
sleep 0.2

# Lambda handler shape: exactly one arg, dotted identifier (no spaces, no slashes,
# no leading dot). `python`, `cloakserve`, `cloaktest`, `bash`, `node` all fail
# this test and pass through to plain exec.
if [ $# -eq 1 ] && \
   echo "$1" | grep -qE '^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$'; then
    if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
        # Local invocation via bundled RIE.
        exec /usr/local/bin/aws-lambda-rie /usr/local/bin/python -m awslambdaric "$@"
    else
        # Real Lambda — runtime API endpoint already provided by the platform.
        exec /usr/local/bin/python -m awslambdaric "$@"
    fi
fi

exec "$@"
