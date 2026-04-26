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

Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/tmp/Xvfb.log 2>&1 &
sleep 0.5

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
