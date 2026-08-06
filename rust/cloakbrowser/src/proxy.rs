//! Proxy resolution: maps a proxy URL or settings into Playwright proxy
//! options and/or Chrome `--proxy-server` args.
//! Direct port of the proxy helpers in Python `cloakbrowser/browser.py`.

use crate::config;
use crate::error::{Error, Result};
use crate::log;

/// Playwright-compatible proxy configuration.
#[derive(Debug, Clone, Default)]
pub struct ProxySettings {
    pub server: String,
    pub bypass: Option<String>,
    pub username: Option<String>,
    pub password: Option<String>,
}

impl ProxySettings {
    pub fn new(server: impl Into<String>) -> Self {
        Self {
            server: server.into(),
            ..Default::default()
        }
    }
}

/// A proxy input accepted by launch helpers.
#[derive(Debug, Clone)]
pub enum Proxy {
    Url(String),
    Settings(ProxySettings),
}

impl From<&str> for Proxy {
    fn from(s: &str) -> Self {
        Proxy::Url(s.to_string())
    }
}

impl From<String> for Proxy {
    fn from(s: String) -> Self {
        Proxy::Url(s)
    }
}

impl From<ProxySettings> for Proxy {
    fn from(s: ProxySettings) -> Self {
        Proxy::Settings(s)
    }
}

/// Result of resolving a proxy: Playwright proxy (or None) plus extra Chrome args.
#[derive(Debug, Clone, Default)]
pub struct ProxyResolution {
    pub playwright_proxy: Option<ProxySettings>,
    pub extra_args: Vec<String>,
}

// -- URL parsing -------------------------------------------------------------

#[derive(Debug, Default, Clone)]
struct ParsedUrl {
    scheme: String,
    username: Option<String>, // None = absent, Some("") = present-but-empty
    password: Option<String>,
    host: String,
    port: Option<u16>,
    path: String,
    query: String,
    fragment: String,
}

/// Prepend `http://` to schemeless proxy URLs.
pub fn ensure_proxy_scheme(proxy_url: &str) -> String {
    if proxy_url.contains("://") {
        proxy_url.to_string()
    } else {
        format!("http://{proxy_url}")
    }
}

fn parse_url(url: &str) -> Result<ParsedUrl> {
    let mut p = ParsedUrl::default();
    let mut rest = url.to_string();

    if let Some(idx) = rest.find("://") {
        p.scheme = rest[..idx].to_lowercase();
        rest = rest[idx + 3..].to_string();
    }

    if let Some(hash_idx) = rest.find('#') {
        p.fragment = rest[hash_idx + 1..].to_string();
        rest = rest[..hash_idx].to_string();
    }

    if let Some(q_idx) = rest.find('?') {
        p.query = rest[q_idx + 1..].to_string();
        rest = rest[..q_idx].to_string();
    }

    let (netloc, path) = if let Some(slash_idx) = rest.find('/') {
        (rest[..slash_idx].to_string(), rest[slash_idx..].to_string())
    } else {
        (rest, String::new())
    };
    p.path = path;

    let (hostport, userinfo) = if let Some(at_idx) = netloc.rfind('@') {
        (
            netloc[at_idx + 1..].to_string(),
            Some(netloc[..at_idx].to_string()),
        )
    } else {
        (netloc, None)
    };

    if let Some(userinfo) = userinfo {
        if let Some(colon) = userinfo.find(':') {
            p.username = Some(userinfo[..colon].to_string());
            p.password = Some(userinfo[colon + 1..].to_string());
        } else {
            p.username = Some(userinfo);
            p.password = None;
        }
    }

    if hostport.starts_with('[') {
        let close = hostport
            .find(']')
            .ok_or_else(|| Error::msg("Invalid IPv6 proxy host"))?;
        p.host = hostport[1..close].to_string();
        let after = &hostport[close + 1..];
        if let Some(port_str) = after.strip_prefix(':') {
            p.port = Some(parse_port(port_str)?);
        }
    } else if let Some(colon) = hostport.rfind(':') {
        p.host = hostport[..colon].to_string();
        p.port = Some(parse_port(&hostport[colon + 1..])?);
    } else {
        p.host = hostport;
    }

    // Python urlparse().hostname lowercases the host.
    p.host = p.host.to_lowercase();
    Ok(p)
}

fn parse_port(s: &str) -> Result<u16> {
    if s.is_empty() {
        return Err(Error::msg("Invalid port: empty"));
    }
    s.parse::<u16>()
        .map_err(|_| Error::msg(format!("Invalid port: {s}")))
}

fn quote(s: &str) -> String {
    urlencoding::encode(s).into_owned()
}

fn unquote(s: &str) -> String {
    urlencoding::decode(s)
        .map(|c| c.into_owned())
        .unwrap_or_else(|_| s.to_string())
}

#[allow(clippy::too_many_arguments)] // mirrors Python urlparse assemble pieces
fn assemble_proxy_url(
    scheme: &str,
    host: &str,
    port: Option<u16>,
    enc_user: &str,
    enc_pass: Option<&str>,
    path: &str,
    query: &str,
    fragment: &str,
) -> String {
    let host = if host.contains(':') {
        format!("[{host}]")
    } else {
        host.to_string()
    };

    let userinfo = if let Some(pass) = enc_pass {
        format!("{enc_user}:{pass}@")
    } else if !enc_user.is_empty() {
        format!("{enc_user}@")
    } else {
        String::new()
    };

    let mut netloc = format!("{userinfo}{host}");
    if let Some(port) = port {
        netloc.push_str(&format!(":{port}"));
    }

    let mut sb = String::new();
    if !scheme.is_empty() {
        sb.push_str(scheme);
        sb.push_str("://");
    }
    sb.push_str(&netloc);
    sb.push_str(path);
    if !query.is_empty() {
        sb.push('?');
        sb.push_str(query);
    }
    if !fragment.is_empty() {
        sb.push('#');
        sb.push_str(fragment);
    }
    sb
}

// -- SOCKS -------------------------------------------------------------------

pub fn is_socks_proxy_url(url: &str) -> bool {
    let lower = url.to_ascii_lowercase();
    lower.starts_with("socks5://") || lower.starts_with("socks5h://")
}

fn is_socks_proxy(proxy: &Proxy) -> bool {
    match proxy {
        Proxy::Url(s) => is_socks_proxy_url(s),
        Proxy::Settings(ps) => is_socks_proxy_url(&ps.server),
    }
}

fn reconstruct_socks_url(proxy: &ProxySettings) -> Result<String> {
    let username = proxy.username.as_deref().unwrap_or("");
    if username.is_empty() {
        return Ok(proxy.server.clone());
    }
    let parsed = parse_url(&proxy.server)?;
    let enc_user = quote(username);
    let enc_pass = proxy
        .password
        .as_ref()
        .filter(|p| !p.is_empty())
        .map(|p| quote(p));
    Ok(assemble_proxy_url(
        &parsed.scheme,
        &parsed.host,
        parsed.port,
        &enc_user,
        enc_pass.as_deref(),
        &parsed.path,
        "",
        "",
    ))
}

fn normalize_socks_string_url(url: &str) -> String {
    let parsed = match parse_url(url) {
        Ok(p) => p,
        Err(e) => {
            log::warning(format!(
                "Malformed SOCKS5 proxy URL, passing through unchanged: {e}"
            ));
            return url.to_string();
        }
    };
    if parsed.username.is_none() && parsed.password.is_none() {
        return url.to_string();
    }
    let raw_user = parsed.username.clone().unwrap_or_default();
    let enc_user = if raw_user.is_empty() {
        String::new()
    } else {
        quote(&unquote(&raw_user))
    };
    let enc_pass = parsed.password.as_ref().map(|p| {
        if p.is_empty() {
            String::new()
        } else {
            quote(&unquote(p))
        }
    });
    let normalized = assemble_proxy_url(
        &parsed.scheme,
        &parsed.host,
        parsed.port,
        &enc_user,
        enc_pass.as_deref(),
        &parsed.path,
        &parsed.query,
        &parsed.fragment,
    );
    if enc_user != raw_user || enc_pass.as_deref() != parsed.password.as_deref() {
        log::info(
            "Auto URL-encoded SOCKS5 proxy credentials (special characters detected). \
             Pre-encode the URL to suppress this notice.",
        );
    }
    normalized
}

// -- HTTP --------------------------------------------------------------------

fn has_credentials(proxy: &Proxy) -> bool {
    match proxy {
        Proxy::Settings(ps) => ps
            .username
            .as_ref()
            .map(|u| !u.is_empty())
            .unwrap_or(false),
        Proxy::Url(s) => s.contains('@'),
    }
}

fn reconstruct_http_url(proxy: &ProxySettings) -> Result<String> {
    let username = proxy.username.as_deref().unwrap_or("");
    if username.is_empty() {
        return Ok(proxy.server.clone());
    }
    let parsed = parse_url(&ensure_proxy_scheme(&proxy.server))?;
    let enc_user = quote(username);
    let enc_pass = proxy
        .password
        .as_ref()
        .filter(|p| !p.is_empty())
        .map(|p| quote(p));
    Ok(assemble_proxy_url(
        &parsed.scheme,
        &parsed.host,
        parsed.port,
        &enc_user,
        enc_pass.as_deref(),
        &parsed.path,
        "",
        "",
    ))
}

fn normalize_http_string_url(url: &str) -> String {
    let normalized = ensure_proxy_scheme(url);
    let parsed = match parse_url(&normalized) {
        Ok(p) => p,
        Err(e) => {
            log::warning(format!(
                "Malformed HTTP proxy URL, passing through unchanged: {e}"
            ));
            return normalized;
        }
    };
    if parsed.username.is_none() && parsed.password.is_none() {
        return normalized;
    }
    let raw_user = parsed.username.clone().unwrap_or_default();
    let enc_user = if raw_user.is_empty() {
        String::new()
    } else {
        quote(&unquote(&raw_user))
    };
    let enc_pass = parsed.password.as_ref().map(|p| {
        if p.is_empty() {
            String::new()
        } else {
            quote(&unquote(p))
        }
    });
    let result = assemble_proxy_url(
        &parsed.scheme,
        &parsed.host,
        parsed.port,
        &enc_user,
        enc_pass.as_deref(),
        &parsed.path,
        &parsed.query,
        &parsed.fragment,
    );
    if enc_user != raw_user || enc_pass.as_deref() != parsed.password.as_deref() {
        log::info(
            "Auto URL-encoded HTTP proxy credentials (special characters detected). \
             Pre-encode the URL to suppress this notice.",
        );
    }
    result
}

fn parse_proxy_url(proxy: &str) -> Result<ProxySettings> {
    let mut normalized = proxy.to_string();
    if proxy.contains('@') && !proxy.contains("://") {
        normalized = format!("http://{proxy}");
    }
    let parsed = parse_url(&normalized)?;
    if parsed.username.as_ref().map(|u| u.is_empty()).unwrap_or(true) {
        return Ok(ProxySettings::new(proxy));
    }

    let mut netloc = parsed.host.clone();
    if let Some(port) = parsed.port {
        netloc.push_str(&format!(":{port}"));
    }
    let mut server = String::new();
    if !parsed.scheme.is_empty() {
        server.push_str(&parsed.scheme);
        server.push_str("://");
    }
    server.push_str(&netloc);
    server.push_str(&parsed.path);

    Ok(ProxySettings {
        server,
        username: parsed.username.map(|u| unquote(&u)),
        password: parsed
            .password
            .filter(|p| !p.is_empty())
            .map(|p| unquote(&p)),
        bypass: None,
    })
}

/// Extract a normalized proxy URL string (for geoip / webrtc).
pub fn extract_proxy_url(proxy: Option<&Proxy>) -> Option<String> {
    match proxy {
        None => None,
        Some(Proxy::Settings(ps)) => {
            if ps.server.is_empty() {
                return None;
            }
            if is_socks_proxy_url(&ps.server) {
                reconstruct_socks_url(ps).ok()
            } else {
                Some(ensure_proxy_scheme(&ps.server))
            }
        }
        Some(Proxy::Url(s)) => Some(ensure_proxy_scheme(s)),
    }
}

/// Resolve a proxy into Playwright options + extra Chrome args.
pub fn resolve(
    proxy: Option<&Proxy>,
    browser_version: Option<&str>,
    license_key: Option<&str>,
) -> Result<ProxyResolution> {
    let Some(proxy) = proxy else {
        return Ok(ProxyResolution::default());
    };

    // SOCKS5: bypass Playwright, pass directly to Chrome via --proxy-server.
    if is_socks_proxy(proxy) {
        return match proxy {
            Proxy::Settings(psd) => {
                let url = reconstruct_socks_url(psd)?;
                let mut extra = vec![format!("--proxy-server={url}")];
                if let Some(ref bypass) = psd.bypass {
                    if !bypass.is_empty() {
                        extra.push(format!("--proxy-bypass-list={bypass}"));
                    }
                }
                Ok(ProxyResolution {
                    playwright_proxy: None,
                    extra_args: extra,
                })
            }
            Proxy::Url(s) => Ok(ProxyResolution {
                playwright_proxy: None,
                extra_args: vec![format!("--proxy-server={}", normalize_socks_string_url(s))],
            }),
        };
    }

    // HTTP/HTTPS with credentials on binaries that support inline auth.
    if has_credentials(proxy)
        && config::binary_supports_http_proxy_inline_auth(license_key, browser_version)
    {
        return match proxy {
            Proxy::Settings(psd) => {
                let url = reconstruct_http_url(psd)?;
                let mut extra = vec![format!("--proxy-server={url}")];
                if let Some(ref bypass) = psd.bypass {
                    if !bypass.is_empty() {
                        extra.push(format!("--proxy-bypass-list={bypass}"));
                    }
                }
                Ok(ProxyResolution {
                    playwright_proxy: None,
                    extra_args: extra,
                })
            }
            Proxy::Url(s) => Ok(ProxyResolution {
                playwright_proxy: None,
                extra_args: vec![format!("--proxy-server={}", normalize_http_string_url(s))],
            }),
        };
    }

    // HTTP/HTTPS without credentials (or older binary): Playwright proxy.
    match proxy {
        Proxy::Settings(dict) => Ok(ProxyResolution {
            playwright_proxy: Some(dict.clone()),
            extra_args: vec![],
        }),
        Proxy::Url(s) => Ok(ProxyResolution {
            playwright_proxy: Some(parse_proxy_url(s)?),
            extra_args: vec![],
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ensure_scheme() {
        assert_eq!(
            ensure_proxy_scheme("1.2.3.4:8080"),
            "http://1.2.3.4:8080"
        );
        assert_eq!(
            ensure_proxy_scheme("socks5://h:1"),
            "socks5://h:1"
        );
    }

    #[test]
    fn socks_detection() {
        assert!(is_socks_proxy_url("socks5://host:1080"));
        assert!(is_socks_proxy_url("socks5h://host:1080"));
        assert!(!is_socks_proxy_url("http://host:8080"));
    }

    #[test]
    fn resolve_socks_string() {
        let p = Proxy::from("socks5://user:pass@host:1080");
        let r = resolve(Some(&p), None, None).unwrap();
        assert!(r.playwright_proxy.is_none());
        assert!(r.extra_args[0].starts_with("--proxy-server=socks5://"));
    }

    #[test]
    fn resolve_http_no_creds() {
        let p = Proxy::from("http://proxy:8080");
        let r = resolve(Some(&p), Some("146.0.7680.177.5"), None).unwrap();
        assert!(r.playwright_proxy.is_some());
        assert!(r.extra_args.is_empty());
        assert_eq!(r.playwright_proxy.unwrap().server, "http://proxy:8080");
    }

    #[test]
    fn parse_url_with_auth() {
        let p = parse_url("http://user:p%40ss@host:8080/path").unwrap();
        assert_eq!(p.scheme, "http");
        assert_eq!(p.username.as_deref(), Some("user"));
        assert_eq!(p.password.as_deref(), Some("p%40ss"));
        assert_eq!(p.host, "host");
        assert_eq!(p.port, Some(8080));
        assert_eq!(p.path, "/path");
    }
}
