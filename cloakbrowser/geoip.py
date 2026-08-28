"""GeoIP-based timezone and locale detection from proxy IP.

Optional feature — requires ``geoip2`` package::

    pip install cloakbrowser[geoip]

Downloads GeoLite2-City.mmdb (~70 MB) on first use, caches in
``~/.cloakbrowser/geoip/``.  Background re-download after 30 days.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("cloakbrowser")

# P3TERX mirror of MaxMind GeoLite2-City — no license key needed
GEOIP_DB_URL = (
    "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb"
)
GEOIP_DB_FILENAME = "GeoLite2-City.mmdb"
GEOIP_UPDATE_INTERVAL = 30 * 86_400  # 30 days
DEFAULT_GEOIP_TIMEOUT_SECONDS = 20.0
GEOIP_TIMEOUT_ENV = "CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS"

# Serializes GeoIP DB downloads within a process so N concurrent launches
# don't each fetch the same ~70 MB file (issue #458). Per-process only.
_GEOIP_DOWNLOAD_LOCK = threading.Lock()

# Country ISO code → BCP 47 locale (covers ~90 % of proxy traffic)
COUNTRY_LOCALE_MAP: dict[str, str] = {
    "US": "en-US", "GB": "en-GB", "AU": "en-AU", "CA": "en-CA", "NZ": "en-NZ",
    "IE": "en-IE", "ZA": "en-ZA", "SG": "en-SG",
    "DE": "de-DE", "AT": "de-AT", "CH": "de-CH",
    "FR": "fr-FR", "BE": "fr-BE",
    "ES": "es-ES", "MX": "es-MX", "AR": "es-AR", "CO": "es-CO", "CL": "es-CL",
    "BR": "pt-BR", "PT": "pt-PT",
    "IT": "it-IT", "NL": "nl-NL",
    "JP": "ja-JP", "KR": "ko-KR", "CN": "zh-CN", "TW": "zh-TW", "HK": "zh-HK",
    "RU": "ru-RU", "UA": "uk-UA", "PL": "pl-PL", "CZ": "cs-CZ", "RO": "ro-RO",
    "IL": "he-IL", "TR": "tr-TR", "SA": "ar-SA", "AE": "ar-AE", "EG": "ar-EG",
    "IN": "hi-IN", "ID": "id-ID", "PH": "en-PH",
    "TH": "th-TH", "VN": "vi-VN", "MY": "ms-MY",
    "SE": "sv-SE", "NO": "nb-NO", "DK": "da-DK", "FI": "fi-FI",
    "GR": "el-GR", "HU": "hu-HU", "BG": "bg-BG",
    # Extended coverage — common residential/mobile proxy exits
    "SI": "sl-SI", "SK": "sk-SK", "HR": "hr-HR", "RS": "sr-RS", "LT": "lt-LT",
    "LV": "lv-LV", "EE": "et-EE", "IS": "is-IS", "LU": "fr-LU", "MT": "en-MT",
    "CY": "el-CY", "MD": "ro-MD", "BY": "ru-BY", "GE": "ka-GE", "AL": "sq-AL",
    "MK": "mk-MK", "BA": "bs-BA",
    "PE": "es-PE", "VE": "es-VE", "EC": "es-EC", "UY": "es-UY", "CR": "es-CR",
    "DO": "es-DO", "GT": "es-GT", "BO": "es-BO", "PY": "es-PY",
    "PK": "en-PK", "BD": "bn-BD", "LK": "si-LK", "KZ": "ru-KZ", "IR": "fa-IR",
    "IQ": "ar-IQ", "JO": "ar-JO", "LB": "ar-LB", "KW": "ar-KW", "QA": "ar-QA",
    "OM": "ar-OM", "BH": "ar-BH",
    "NG": "en-NG", "KE": "en-KE", "MA": "fr-MA", "DZ": "ar-DZ", "TN": "ar-TN",
    "GH": "en-GH",
    "AM": "hy-AM", "AZ": "az-AZ", "UZ": "uz-UZ", "KG": "ky-KG", "TJ": "tg-TJ",
    "TM": "tk-TM",
    "ME": "sr-ME", "XK": "sq-XK", "LI": "de-LI", "MC": "fr-MC", "AD": "ca-AD",
    "MM": "my-MM", "KH": "km-KH", "LA": "lo-LA", "MN": "mn-MN", "BN": "ms-BN",
    "MO": "zh-MO",
    "YE": "ar-YE", "SY": "ar-SY", "PS": "ar-PS", "LY": "ar-LY",
    "ET": "am-ET", "TZ": "sw-TZ", "UG": "en-UG", "SN": "fr-SN", "CI": "fr-CI",
    "CM": "fr-CM", "AO": "pt-AO", "MZ": "pt-MZ", "ZM": "en-ZM", "ZW": "en-ZW",
    "HN": "es-HN", "NI": "es-NI", "SV": "es-SV", "PA": "es-PA", "JM": "en-JM",
    "TT": "en-TT", "PR": "es-PR",
}


def resolve_proxy_geo(proxy_url: str | None) -> tuple[str | None, str | None]:
    """Resolve timezone and locale from a proxy's IP address.

    Returns ``(timezone, locale)``. Raises when the exit IP, database, or
    database lookup cannot be resolved.

    When *proxy_url* is falsy, the machine's own public IP is used instead
    (direct HTTP to the echo services, no proxy).
    """
    tz, locale, _ip = resolve_proxy_geo_with_ip(proxy_url)
    return tz, locale


def resolve_proxy_geo_with_ip(
    proxy_url: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve timezone, locale, and exit IP from a proxy.

    Returns ``(timezone, locale, exit_ip)``.  The exit IP is a free bonus
    from the lookup — reused for WebRTC spoofing without an extra HTTP call.

    When *proxy_url* is falsy, the egress IP is the machine's own public IP
    (echo services queried directly, no proxy), so geoip works proxy-free.
    """
    try:
        import geoip2.database  # noqa: F811
    except ImportError:
        raise ImportError(
            "geoip2 is required for geoip=True. Install it with:\n"
            "  pip install 'cloakbrowser[geoip]'"
        ) from None

    # Ensure the DB first — the download must NOT be bounded by the resolution
    # timeout (a first-use ~70MB fetch legitimately outlasts it).
    db_path = _ensure_geoip_db()

    timeout = _get_geoip_timeout_seconds()
    deadline = _deadline_from_timeout(timeout)

    # Exit IP (through proxy, or the machine's own public IP when proxy_url is
    # falsy) is most accurate — gateway DNS may differ from exit. Resolved even
    # when the DB is unavailable: the IP does not need the DB, and dropping it on
    # a DB hiccup would let WebRTC fall back to the real IP behind a proxy while
    # the connection shows the proxy IP — a real deanonymization.
    ip = _resolve_exit_ip(proxy_url, timeout=_remaining_seconds(deadline))
    # Hostname fallback only applies to a proxy; no proxy → echo services only
    if ip is None and proxy_url and not _deadline_expired(deadline):
        ip = _resolve_proxy_ip(proxy_url)
    if ip is None or _deadline_expired(deadline):
        if deadline is not None and _deadline_expired(deadline):
            raise RuntimeError(f"GeoIP resolution timed out after {timeout:.1f}s")
        raise RuntimeError("GeoIP resolution failed: could not discover the egress IP")

    if db_path is None:
        raise RuntimeError("GeoIP resolution failed: GeoIP database is unavailable")

    try:
        with geoip2.database.Reader(str(db_path)) as reader:
            resp = reader.city(ip)
            timezone = resp.location.time_zone
            country = resp.country.iso_code
            locale = COUNTRY_LOCALE_MAP.get(country) if country else None
            logger.debug(
                "GeoIP: %s → tz=%s, country=%s, locale=%s",
                ip, timezone, country, locale,
            )
            return timezone, locale, ip
    except Exception as exc:
        raise RuntimeError(f"GeoIP lookup failed for {ip}: {exc}") from exc


# ---------------------------------------------------------------------------
# Proxy IP resolution
# ---------------------------------------------------------------------------


def _resolve_proxy_ip(proxy_url: str) -> str | None:
    """Extract proxy hostname from URL and resolve to an IP address."""
    try:
        hostname = urlparse(proxy_url).hostname
        if not hostname:
            return None

        # Already a literal IP?
        try:
            socket.inet_pton(socket.AF_INET, hostname)
            return hostname
        except OSError:
            pass
        try:
            socket.inet_pton(socket.AF_INET6, hostname)
            return hostname
        except OSError:
            pass

        # DNS resolve (returns first result, handles both v4/v6)
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if results:
            ip = results[0][4][0]
            logger.debug("Resolved proxy %s → %s", hostname, ip)
            return ip
        return None
    except Exception as exc:
        logger.warning("Failed to resolve proxy hostname: %s", exc)
        return None


def _is_private_ip(ip: str) -> bool:
    """Check if an IP address is private/internal (not routable on the internet)."""
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


# IP echo services — fast, no auth, return just the IP
_IP_ECHO_URLS = [
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
    "https://ifconfig.me/ip",
]


def _get_geoip_timeout_seconds() -> float:
    raw = os.getenv(GEOIP_TIMEOUT_ENV)
    if not raw:
        return DEFAULT_GEOIP_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        timeout = float("nan")
    if not math.isfinite(timeout):
        logger.warning(
            "Invalid %s=%r; using %.1fs",
            GEOIP_TIMEOUT_ENV,
            raw,
            DEFAULT_GEOIP_TIMEOUT_SECONDS,
        )
        return DEFAULT_GEOIP_TIMEOUT_SECONDS
    return max(timeout, 0.0)


def _deadline_from_timeout(timeout: float) -> float | None:
    if timeout <= 0:
        return None
    return time.monotonic() + timeout


def _remaining_seconds(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(deadline - time.monotonic(), 0.0)


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def resolve_proxy_exit_ip(proxy_url: str | None) -> str | None:
    """Resolve the egress IP, bounded by the GeoIP timeout.

    With a proxy this is the proxy's exit IP; with no proxy it is the
    machine's own public IP (echo services queried directly).
    """
    timeout = _get_geoip_timeout_seconds()
    deadline = _deadline_from_timeout(timeout)
    ip = _resolve_exit_ip(proxy_url, timeout=timeout)
    if ip is None and _deadline_expired(deadline):
        logger.warning("Proxy exit-IP resolution timed out after %.1fs", timeout)
    return ip


def _resolve_exit_ip(proxy_url: str | None, timeout: float | None = None) -> str | None:
    """Discover the egress IP via the echo services.

    Through *proxy_url* when given (the proxy's exit IP); directly (no proxy)
    when *proxy_url* is falsy — that returns the machine's own public IP.
    """
    import httpx

    deadline = _deadline_from_timeout(timeout or 0)

    for url in _IP_ECHO_URLS:
        try:
            remaining = _remaining_seconds(deadline)
            if remaining is not None and remaining <= 0:
                return None
            request_timeout = min(10.0, remaining) if remaining is not None else 10.0
            resp = httpx.get(url, proxy=proxy_url or None, timeout=request_timeout)
            resp.raise_for_status()
            ip = resp.text.strip()
            # Validate it looks like an IP
            ipaddress.ip_address(ip)
            logger.debug("Exit IP via %s: %s", url, ip)
            return ip
        except httpx.UnsupportedProtocol:
            logger.warning(
                "SOCKS5 proxy requires socksio: pip install 'cloakbrowser[geoip]'"
            )
            return None
        except Exception:
            continue
    logger.warning("Failed to discover exit IP through proxy")
    return None


# ---------------------------------------------------------------------------
# GeoIP database management
# ---------------------------------------------------------------------------


def _get_geoip_dir() -> Path:
    from .config import get_cache_dir

    return get_cache_dir() / "geoip"


def _ensure_geoip_db() -> Path | None:
    """Return path to GeoLite2-City.mmdb, downloading on first use."""
    db_path = _get_geoip_dir() / GEOIP_DB_FILENAME

    if db_path.exists():
        _maybe_trigger_update(db_path)
        return db_path

    # Serialize concurrent first-use downloads: only one launch fetches the
    # shared file, the rest wait and reuse it.
    with _GEOIP_DOWNLOAD_LOCK:
        if db_path.exists():  # another launch finished while we waited
            return db_path
        try:
            _download_geoip_db(db_path)
            return db_path
        except Exception as exc:
            logger.warning("Failed to download GeoIP database: %s", exc)
            return None


def _download_geoip_db(dest: Path) -> None:
    """Atomic download of GeoLite2-City.mmdb via httpx."""
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading GeoIP database (~70 MB) …")

    tmp_fd, tmp_name = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with httpx.stream(
            "GET", GEOIP_DB_URL, follow_redirects=True, timeout=300.0
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            last_pct = -1
            with open(tmp_fd, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        if pct >= last_pct + 10:
                            last_pct = pct
                            logger.info("GeoIP download: %d %%", pct)

        os.replace(tmp_path, dest)  # atomic overwrite (Windows-safe, unlike rename)
        logger.info("GeoIP database ready: %s", dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _maybe_trigger_update(db_path: Path) -> None:
    """Re-download in background if DB is older than 30 days."""
    try:
        age = time.time() - db_path.stat().st_mtime
        if age < GEOIP_UPDATE_INTERVAL:
            return
    except OSError:
        return

    def _bg() -> None:
        # Skip if a download (initial or refresh) is already running.
        if not _GEOIP_DOWNLOAD_LOCK.acquire(blocking=False):
            return
        try:
            _download_geoip_db(db_path)
        except Exception:
            logger.debug("Background GeoIP update failed", exc_info=True)
        finally:
            _GEOIP_DOWNLOAD_LOCK.release()

    threading.Thread(target=_bg, daemon=True).start()
