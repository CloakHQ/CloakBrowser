#!/bin/bash
# Clean up any stale Xvfb lock left behind by a previous container instance.
# `/tmp` is not a tmpfs in this image, so on `docker restart` the previous
# container's `/tmp/.X99-lock` survives, and Xvfb refuses to start with an
# existing lock — leaving the container with no X server, every Chrome
# launch dying with "Missing X server or $DISPLAY", and `cloakserve`
# returning 502 forever. See CloakHQ/CloakBrowser#283.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Start Xvfb for headed mode (Turnstile, CAPTCHAs), then run user command
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 1
exec "$@"
