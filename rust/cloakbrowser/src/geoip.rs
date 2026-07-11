//! GeoIP-based timezone and locale detection from a proxy IP.
//! Direct port of Python `cloakbrowser/geoip.py` / .NET `GeoIp.cs`.
//!
//! Enabled with the `geoip` feature (default). Downloads GeoLite2-City.mmdb
//! (~70 MB) on first use into `~/.cloakbrowser/geoip/`.

use std::collections::HashMap;
use std::net::IpAddr;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::SystemTime;

use crate::config;
use crate::error::{Error, Result};
use crate::log;
use crate::proxy::{self, Proxy};
use crate::version::VERSION;

const GEOIP_DB_URL: &str =
    "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb";
const GEOIP_DB_FILENAME: &str = "GeoLite2-City.mmdb";
const GEOIP_UPDATE_INTERVAL: u64 = 30 * 86_400; // 30 days
const DEFAULT_GEOIP_TIMEOUT_SECONDS: f64 = 5.0;
const GEOIP_TIMEOUT_ENV: &str = "CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS";

const IP_ECHO_URLS: &[&str] = &[
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
    "https://ifconfig.me/ip",
];

fn country_locale_map() -> &'static HashMap<&'static str, &'static str> {
    static MAP: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    MAP.get_or_init(|| {
        HashMap::from([
            ("US", "en-US"),
            ("GB", "en-GB"),
            ("AU", "en-AU"),
            ("CA", "en-CA"),
            ("NZ", "en-NZ"),
            ("IE", "en-IE"),
            ("ZA", "en-ZA"),
            ("SG", "en-SG"),
            ("DE", "de-DE"),
            ("AT", "de-AT"),
            ("CH", "de-CH"),
            ("FR", "fr-FR"),
            ("BE", "fr-BE"),
            ("ES", "es-ES"),
            ("MX", "es-MX"),
            ("AR", "es-AR"),
            ("CO", "es-CO"),
            ("CL", "es-CL"),
            ("BR", "pt-BR"),
            ("PT", "pt-PT"),
            ("IT", "it-IT"),
            ("NL", "nl-NL"),
            ("JP", "ja-JP"),
            ("KR", "ko-KR"),
            ("CN", "zh-CN"),
            ("TW", "zh-TW"),
            ("HK", "zh-HK"),
            ("RU", "ru-RU"),
            ("UA", "uk-UA"),
            ("PL", "pl-PL"),
            ("CZ", "cs-CZ"),
            ("RO", "ro-RO"),
            ("IL", "he-IL"),
            ("TR", "tr-TR"),
            ("SA", "ar-SA"),
            ("AE", "ar-AE"),
            ("EG", "ar-EG"),
            ("IN", "hi-IN"),
            ("ID", "id-ID"),
            ("PH", "en-PH"),
            ("TH", "th-TH"),
            ("VN", "vi-VN"),
            ("MY", "ms-MY"),
            ("SE", "sv-SE"),
            ("NO", "nb-NO"),
            ("DK", "da-DK"),
            ("FI", "fi-FI"),
            ("GR", "el-GR"),
            ("HU", "hu-HU"),
            ("BG", "bg-BG"),
            ("SI", "sl-SI"),
            ("SK", "sk-SK"),
            ("HR", "hr-HR"),
            ("RS", "sr-RS"),
            ("LT", "lt-LT"),
            ("LV", "lv-LV"),
            ("EE", "et-EE"),
            ("IS", "is-IS"),
            ("LU", "fr-LU"),
            ("MT", "en-MT"),
            ("CY", "el-CY"),
            ("MD", "ro-MD"),
            ("BY", "ru-BY"),
            ("GE", "ka-GE"),
            ("AL", "sq-AL"),
            ("MK", "mk-MK"),
            ("BA", "bs-BA"),
            ("PE", "es-PE"),
            ("VE", "es-VE"),
            ("EC", "es-EC"),
            ("UY", "es-UY"),
            ("CR", "es-CR"),
            ("DO", "es-DO"),
            ("GT", "es-GT"),
            ("BO", "es-BO"),
            ("PY", "es-PY"),
            ("PK", "en-PK"),
            ("BD", "bn-BD"),
            ("LK", "si-LK"),
            ("KZ", "ru-KZ"),
            ("IR", "fa-IR"),
            ("IQ", "ar-IQ"),
            ("JO", "ar-JO"),
            ("LB", "ar-LB"),
            ("KW", "ar-KW"),
            ("QA", "ar-QA"),
            ("OM", "ar-OM"),
            ("BH", "ar-BH"),
            ("NG", "en-NG"),
            ("KE", "en-KE"),
            ("MA", "fr-MA"),
            ("DZ", "ar-DZ"),
            ("TN", "ar-TN"),
            ("GH", "en-GH"),
            ("AM", "hy-AM"),
            ("AZ", "az-AZ"),
            ("UZ", "uz-UZ"),
            ("KG", "ky-KG"),
            ("TJ", "tg-TJ"),
            ("TM", "tk-TM"),
            ("ME", "sr-ME"),
            ("XK", "sq-XK"),
            ("LI", "de-LI"),
            ("MC", "fr-MC"),
            ("AD", "ca-AD"),
            ("MM", "my-MM"),
            ("KH", "km-KH"),
            ("LA", "lo-LA"),
            ("MN", "mn-MN"),
            ("BN", "ms-BN"),
            ("MO", "zh-MO"),
            ("YE", "ar-YE"),
            ("SY", "ar-SY"),
            ("PS", "ar-PS"),
            ("LY", "ar-LY"),
            ("ET", "am-ET"),
            ("TZ", "sw-TZ"),
            ("UG", "en-UG"),
            ("SN", "fr-SN"),
            ("CI", "fr-CI"),
            ("CM", "fr-CM"),
            ("AO", "pt-AO"),
            ("MZ", "pt-MZ"),
            ("ZM", "en-ZM"),
            ("ZW", "en-ZW"),
            ("HN", "es-HN"),
            ("NI", "es-NI"),
            ("SV", "es-SV"),
            ("PA", "es-PA"),
            ("JM", "en-JM"),
            ("TT", "en-TT"),
            ("PR", "es-PR"),
        ])
    })
}

fn geoip_db_path() -> PathBuf {
    config::get_cache_dir().join("geoip").join(GEOIP_DB_FILENAME)
}

fn get_geoip_timeout_seconds() -> f64 {
    std::env::var(GEOIP_TIMEOUT_ENV)
        .ok()
        .and_then(|s| s.parse().ok())
        .filter(|&v| v > 0.0)
        .unwrap_or(DEFAULT_GEOIP_TIMEOUT_SECONDS)
}

fn http_client(timeout_secs: f64) -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs_f64(timeout_secs.max(1.0)))
        .user_agent(format!("cloakbrowser-rust/{VERSION}"))
        .build()?)
}

/// Ensure GeoLite2-City.mmdb is present. Downloads on first use.
pub async fn ensure_geoip_db() -> Result<PathBuf> {
    let path = geoip_db_path();
    if path.exists() {
        if let Ok(meta) = path.metadata() {
            if let Ok(modified) = meta.modified() {
                if let Ok(age) = SystemTime::now().duration_since(modified) {
                    if age.as_secs() < GEOIP_UPDATE_INTERVAL {
                        return Ok(path);
                    }
                }
            }
        }
        // Stale: try refresh in place; keep old on failure.
        if download_geoip_db(&path).await.is_ok() {
            return Ok(path);
        }
        return Ok(path);
    }

    download_geoip_db(&path).await?;
    Ok(path)
}

async fn download_geoip_db(path: &Path) -> Result<()> {
    log::info(format!("Downloading GeoLite2-City database to {}...", path.display()));
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let client = http_client(600.0)?;
    let resp = client.get(GEOIP_DB_URL).send().await?.error_for_status()?;
    let bytes = resp.bytes().await?;
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, &bytes)?;
    std::fs::rename(&tmp, path)?;
    log::info(format!(
        "GeoIP database ready ({} MB)",
        bytes.len() / (1024 * 1024)
    ));
    Ok(())
}

/// Resolve the exit IP through the proxy (or machine public IP when proxy is None).
pub async fn resolve_proxy_exit_ip(proxy_url: Option<&str>) -> Option<String> {
    let timeout = get_geoip_timeout_seconds();
    let client = build_proxy_client(proxy_url, timeout).ok()?;

    for url in IP_ECHO_URLS {
        if let Ok(resp) = client.get(*url).send().await {
            if resp.status().is_success() {
                if let Ok(text) = resp.text().await {
                    let ip = text.trim();
                    if ip.parse::<IpAddr>().is_ok() {
                        return Some(ip.to_string());
                    }
                }
            }
        }
    }
    None
}

fn build_proxy_client(proxy_url: Option<&str>, timeout: f64) -> Result<reqwest::Client> {
    let mut builder = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs_f64(timeout.max(1.0)))
        .user_agent(format!("cloakbrowser-rust/{VERSION}"));

    if let Some(url) = proxy_url {
        let proxy = reqwest::Proxy::all(url)
            .map_err(|e| Error::msg(format!("Invalid proxy for geoip: {e}")))?;
        builder = builder.proxy(proxy);
    }

    Ok(builder.build()?)
}

/// Resolve timezone, locale, and exit IP from a proxy.
/// Never panics; returns None fields on failure.
pub async fn resolve_proxy_geo_with_ip(
    proxy_url: Option<&str>,
) -> (Option<String>, Option<String>, Option<String>) {
    #[cfg(not(feature = "geoip"))]
    {
        log::warning(
            "geoip requested but cloakbrowser was built without the `geoip` feature. \
             Enable it with: cloakbrowser = { version = \"...\", features = [\"geoip\"] }",
        );
        let exit_ip = resolve_proxy_exit_ip(proxy_url).await;
        return (None, None, exit_ip);
    }

    #[cfg(feature = "geoip")]
    {
        let exit_ip = resolve_proxy_exit_ip(proxy_url).await;

        let db_path = match ensure_geoip_db().await {
            Ok(p) => p,
            Err(e) => {
                log::warning(format!("GeoIP database unavailable: {e}"));
                return (None, None, exit_ip);
            }
        };

        let Some(ip_str) = exit_ip
            .clone()
            .or_else(|| proxy_url.and_then(host_from_proxy_url))
        else {
            return (None, None, exit_ip);
        };

        let ip: IpAddr = match ip_str.parse() {
            Ok(ip) => ip,
            Err(_) => match resolve_hostname_to_ip(&ip_str) {
                Some(ip) => ip,
                None => return (None, None, exit_ip),
            },
        };

        match lookup_geo(&db_path, ip) {
            Ok((tz, locale)) => (tz, locale, exit_ip),
            Err(e) => {
                log::debug(format!("GeoIP lookup failed for {ip}: {e}"));
                (None, None, exit_ip)
            }
        }
    }
}

#[cfg(feature = "geoip")]
fn lookup_geo(db_path: &Path, ip: IpAddr) -> Result<(Option<String>, Option<String>)> {
    let reader = maxminddb::Reader::open_readfile(db_path)
        .map_err(|e| Error::msg(format!("Failed to open GeoIP DB: {e}")))?;

    let city: maxminddb::geoip2::City = reader
        .lookup(ip)
        .map_err(|e| Error::msg(format!("GeoIP lookup error: {e}")))?;

    let timezone = city
        .location
        .as_ref()
        .and_then(|l| l.time_zone)
        .map(|s| s.to_string());

    let country = city
        .country
        .as_ref()
        .and_then(|c| c.iso_code)
        .map(|s| s.to_string());

    let locale = country.and_then(|c| {
        country_locale_map()
            .get(c.as_str())
            .map(|s| s.to_string())
    });

    Ok((timezone, locale))
}

fn host_from_proxy_url(url: &str) -> Option<String> {
    let parsed = url::Url::parse(&proxy::ensure_proxy_scheme(url)).ok()?;
    parsed.host_str().map(|s| s.to_string())
}

fn resolve_hostname_to_ip(host: &str) -> Option<IpAddr> {
    use std::net::ToSocketAddrs;
    (host, 0u16)
        .to_socket_addrs()
        .ok()?
        .next()
        .map(|a| a.ip())
}

/// Auto-fill timezone/locale from the egress IP when geoip is enabled.
/// Returns `(timezone, locale, exit_ip)`.
pub async fn maybe_resolve_geoip(
    geoip: bool,
    proxy: Option<&Proxy>,
    timezone: Option<String>,
    locale: Option<String>,
) -> (Option<String>, Option<String>, Option<String>) {
    if !geoip {
        return (timezone, locale, None);
    }

    let proxy_url = proxy.and_then(|p| proxy::extract_proxy_url(Some(p)));

    // When both tz/locale are explicit, only resolve exit IP for WebRTC —
    // and only when a proxy is present.
    if timezone.is_some() && locale.is_some() {
        let exit_ip = if proxy_url.is_some() {
            resolve_proxy_exit_ip(proxy_url.as_deref()).await
        } else {
            None
        };
        return (timezone, locale, exit_ip);
    }

    let (geo_tz, geo_locale, exit_ip) =
        resolve_proxy_geo_with_ip(proxy_url.as_deref()).await;
    (
        timezone.or(geo_tz),
        locale.or(geo_locale),
        exit_ip,
    )
}
