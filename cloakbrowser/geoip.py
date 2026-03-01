"""GeoIP-based timezone and locale detection from proxy IP.

Optional feature — requires ``geoip2`` package::

    pip install cloakbrowser[geoip]

Downloads GeoLite2-City.mmdb (~70 MB) on first use, caches in
``~/.cloakbrowser/geoip/``.  Background re-download after 30 days.
"""

from __future__ import annotations

import ipaddress
import logging
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
}


def resolve_proxy_geo(proxy_url: str) -> tuple[str | None, str | None]:
    """Resolve timezone and locale from a proxy's IP address.

    Returns ``(timezone, locale)`` — either or both may be ``None`` on
    failure (missing dep, DB download error, lookup miss).  Never raises.
    """
    try:
        import geoip2.database  # noqa: F811
    except ImportError:
        raise ImportError(
            "geoip2 is required for geoip=True. Install it with:\n"
            "  pip install cloakbrowser[geoip]"
        ) from None

    db_path = _ensure_geoip_db()
    if db_path is None:
        return None, None

    # Exit IP (through proxy) is most accurate — gateway DNS may differ from exit
    ip = _resolve_exit_ip(proxy_url)
    if ip is None:
        ip = _resolve_proxy_ip(proxy_url)
    if ip is None:
        return None, None

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
            return timezone, locale
    except Exception as exc:
        logger.debug("GeoIP lookup failed for %s: %s", ip, exc)
        return None, None


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
        logger.debug("Failed to resolve proxy hostname: %s", exc)
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


def _resolve_exit_ip(proxy_url: str) -> str | None:
    """Discover the proxy's actual exit IP by connecting through it."""
    import httpx

    for url in _IP_ECHO_URLS:
        try:
            resp = httpx.get(url, proxy=proxy_url, timeout=10.0)
            resp.raise_for_status()
            ip = resp.text.strip()
            # Validate it looks like an IP
            ipaddress.ip_address(ip)
            logger.debug("Exit IP via %s: %s", url, ip)
            return ip
        except Exception:
            continue
    logger.debug("Failed to discover exit IP through proxy")
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

        tmp_path.rename(dest)
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
        try:
            _download_geoip_db(db_path)
        except Exception:
            logger.debug("Background GeoIP update failed", exc_info=True)

    threading.Thread(target=_bg, daemon=True).start()
