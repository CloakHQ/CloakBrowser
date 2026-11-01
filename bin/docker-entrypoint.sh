#!/bin/bash
# Clean up any stale Xvfb lock left behind by a previous container instance.
# `/tmp` is not a tmpfs in this image, so on `docker restart` the previous
# container's `/tmp/.X99-lock` survives, and Xvfb refuses to start with an
# existing lock — leaving the container with no X server, every Chrome
# launch dying with "Missing X server or $DISPLAY", and `cloakserve`
# returning 502 forever. See CloakHQ/CloakBrowser#283.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Start Xvfb for headed mode (Turnstile, CAPTCHAs), then run user command.
# setsid: its own session, so Ctrl+C in `docker run -it` reaches only the user's
# command, not the X server (which otherwise dies printing "XIO: fatal IO error").
setsid Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &

# Wait for the X server to actually accept connections before starting the WM.
# A blind `sleep 1` races under a CPU-starved start: openbox can come up before
# X is ready, fail to connect, and never retry — leaving --start-maximized a
# silent no-op for the container's whole life. Poll instead (xdotool is already
# installed and needs a live X server to answer). Bounded to ~10s.
for _ in $(seq 1 50); do
  DISPLAY=:99 xdotool getdisplaygeometry >/dev/null 2>&1 && break
  sleep 0.2
done

# Window manager so headed --start-maximized is honored (bare Xvfb has no WM;
# without one the flag is a silent no-op and the window stays un-maximized).
DISPLAY=:99 setsid openbox &

# Opt-in: fetch the Widevine CDM so persistent contexts present as a real
# Chrome (a DRM/EME probe is used by some bot detectors). Off by default — only
# runs when CLOAKBROWSER_FETCH_WIDEVINE is set, and never if the user already
# pointed at a CDM or disabled seeding. The CDM is fetched per-container from
# Google's component server (the same source Chrome uses), cached in the
# ~/.cloakbrowser volume, and is best-effort: a failure must never block launch.
_fetch_widevine="${CLOAKBROWSER_FETCH_WIDEVINE:-}"
case "${_fetch_widevine,,}" in
  1|true|yes|on)
    # printf (not echo) so a value like `-n` isn't swallowed as a flag.
    if [ -z "${CLOAKBROWSER_WIDEVINE_CDM:-}" ] && \
       ! printf '%s' "${CLOAKBROWSER_WIDEVINE:-}" | grep -qiE '^(0|false|off|no)$'; then
      # Fetch to the default location (the version-independent cache root,
      # ~/.cloakbrowser/WidevineCdm). The wrapper's auto-detection
      # (cloakbrowser/widevine.py, js/src/widevine.ts) falls back to this path
      # after the per-binary dir, so the CDM is discoverable by ANY process (CMD
      # or `docker exec`) and ANY binary version with no env
      # var. Best-effort: a failure must never block launch.
      python /usr/local/bin/fetch-widevine.py --quiet \
        || echo "[cloakbrowser] Widevine fetch failed; continuing without it" >&2
    fi
    ;;
esac

exec "$@"
