# CloakBrowser for Rust

A **Rust** port of the [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) wrapper —
stealth Chromium that passes bot-detection tests, built on top of
[`playwright-rs`](https://crates.io/crates/playwright-rs).

CloakBrowser is a thin wrapper around a closed-source, source-level patched
Chromium binary. This port reproduces the wrapper functionality with identical
behavior to the Python, JavaScript, and .NET clients — same launch flags, same
proxy / GeoIP / WebRTC logic, same download verification (Ed25519 + SHA-256).

> **Status:** Community-style client (like `dotnet/`). Core launch path is
> complete; the transparent **humanize** layer is reserved for a follow-up.

---

## Table of contents

- [Feature matrix](#feature-matrix)
- [Requirements](#requirements)
- [Installation](#installation)
- [Project layout](#project-layout)
- [Quick start](#quick-start)
- [Launch API](#launch-api)
- [CLI](#cli)
- [Environment variables](#environment-variables)
- [Building & testing](#building--testing)
- [Mapping to the Python source](#mapping-to-the-python-source)
- [License](#license)

---

## Feature matrix

| Capability | Status | Source |
| --- | :---: | --- |
| Automatic binary **download / cache / auto-update** (SHA-256 + Ed25519) | ✅ | `download.rs`, `config.rs` |
| **Stealth launch args** (random fingerprint seed, platform spoofing) | ✅ | `launch.rs`, `config.rs` |
| **Proxy** — HTTP/HTTPS + SOCKS5, inline URL-encoded credentials | ✅ | `proxy.rs` |
| **GeoIP** timezone/locale from proxy exit IP (MaxMind GeoLite2) | ✅ | `geoip.rs` (`geoip` feature) |
| **WebRTC** IP spoofing (`--fingerprint-webrtc-ip=auto`) | ✅ | `launch.rs` |
| **Pro license** routing + env injection | ✅ | `license.rs` |
| **Persistent contexts** | ✅ | `launch_persistent_context` + Widevine hint |
| **Humanize** — Bezier mouse, human typing, scrolling | ✅ | `human/` (`HumanPage`) |
| **CLI** (`install` / `info` / `update` / `clear-cache`) | ✅ | `cloakbrowser-cli` |

---

## Requirements

| Dependency | Version | Why |
| --- | --- | --- |
| Rust | **1.75+** (edition 2021) | toolchain |
| `playwright-rs` | **0.14** | browser automation |
| `tokio` | **1.x** | async runtime |

On first Playwright use, the driver/browsers may need a one-time install
(`playwright-rs` handles its own driver). CloakBrowser separately downloads its
patched Chromium into `~/.cloakbrowser/`.

---

## Installation

### As a library (path / git)

```toml
[dependencies]
cloakbrowser = { path = "rust/cloakbrowser" }   # monorepo
# or
# cloakbrowser = { git = "https://github.com/CloakHQ/CloakBrowser", path = "rust/cloakbrowser" }
tokio = { version = "1", features = ["rt-multi-thread", "macros"] }
```

Disable GeoIP if you do not need it:

```toml
cloakbrowser = { path = "rust/cloakbrowser", default-features = false }
```

### CLI

```bash
cd rust
cargo install --path cloakbrowser-cli
cloakbrowser install
cloakbrowser info --quick
```

The patched Chromium binary downloads automatically on first launch, cached under
`~/.cloakbrowser` (override with `CLOAKBROWSER_CACHE_DIR`).

---

## Project layout

```
rust/
├── Cargo.toml                       # workspace
├── README.md
├── cloakbrowser/                    # the library
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs
│       ├── config.rs                # <- cloakbrowser/config.py
│       ├── download.rs              # <- cloakbrowser/download.py
│       ├── license.rs               # <- cloakbrowser/license.py
│       ├── geoip.rs                 # <- cloakbrowser/geoip.py
│       ├── proxy.rs                 # <- browser.py proxy helpers
│       ├── launch.rs                # <- browser.py launch / build_args
│       ├── human/                   # <- cloakbrowser/human/*
│       │   ├── config.rs / mouse.rs / keyboard.rs / scroll.rs / page.rs
│       ├── widevine.rs              # <- cloakbrowser/widevine.py
│       ├── options.rs               # launch + persistent context options
│       ├── diagnostics.rs           # CLI info/doctor
│       ├── log.rs / error.rs / version.rs
├── cloakbrowser-cli/                # <- cloakbrowser/__main__.py
│   └── src/main.rs
└── examples/
    └── basic.rs
```

---

## Quick start

```rust
use cloakbrowser::{launch, LaunchOptions};

#[tokio::main]
async fn main() -> cloakbrowser::Result<()> {
    let browser = launch(LaunchOptions {
        headless: true,
        ..Default::default()
    })
    .await?;

    let page = browser.new_page().await?;
    let _ = page.goto("https://bot.incolumitas.com/", None).await;
    println!("{}", page.title().await.unwrap_or_default());
    browser.close().await?;
    Ok(())
}
```

With proxy + GeoIP:

```rust
let browser = launch(LaunchOptions {
    headless: false,
    proxy: Some("http://user:pass@residential-proxy:port".into()),
    geoip: true,
    ..Default::default()
})
.await?;
```

### Humanize

Rust cannot monkey-patch Playwright's `Page` (same constraint as .NET). Use
[`HumanPage`] for humanized interactions:

```rust
use cloakbrowser::{launch, LaunchOptions, HumanPreset};

let browser = launch(LaunchOptions {
    humanize: true,
    human_preset: HumanPreset::Default, // or Careful
    ..Default::default()
})
.await?;

let mut page = browser.new_human_page().await?;
page.goto("https://example.com").await?;
page.fill("#email", "user@example.com").await?;
page.click("#submit").await?;
// raw Playwright page still available:
let _ = page.page().title().await;
```

| Method | Behavior |
| --- | --- |
| `click` / `hover` | Bezier mouse path, aim delay, hold |
| `type_text` / `fill` | Per-key timing, mistypes, CDP shift symbols |
| `scroll_to` | Accel → cruise → decel wheel bursts |
| `move_to` | Explicit Bezier move |

---

## Launch API

`launch(LaunchOptions)` returns a [`CloakBrowser`] that owns the Playwright
driver and browser process. Call `close().await` when done.

| Field | Default | Notes |
| --- | --- | --- |
| `headless` | `true` | |
| `proxy` | `None` | URL string or `ProxySettings` |
| `args` | `None` | Extra Chromium flags |
| `stealth_args` | `true` | Fingerprint seed + platform |
| `timezone` / `locale` | `None` | Or filled by `geoip` |
| `geoip` | `false` | Requires `geoip` feature |
| `humanize` | `false` | Enables config for `new_human_page()` |
| `human_preset` | `Default` | `Default` or `Careful` |
| `license_key` | `None` | Also `CLOAKBROWSER_LICENSE_KEY` |
| `browser_version` | `None` | Also `CLOAKBROWSER_VERSION` |

### Persistent context

```rust
use cloakbrowser::{launch_persistent_context, LaunchContextOptions, ViewportOption};

let ctx = launch_persistent_context(
    "./my-profile",
    LaunchContextOptions {
        headless: false,
        humanize: true,
        viewport: ViewportOption::Auto, // no_viewport when headed
        user_agent: None,
        ..Default::default()
    },
)
.await?;

let page = ctx.new_page().await?;
// ... cookies/localStorage persist in ./my-profile
ctx.close().await?;
```

| Field | Notes |
| --- | --- |
| `viewport` | `Auto` / `Size { w, h }` / `NoViewport` |
| `user_agent` | Optional custom UA |
| `color_scheme` | `light` / `dark` / `no-preference` |
| `storage_state_path` | Playwright storage-state JSON path |

Timezone/locale still go through **binary fingerprint flags** (not CDP). Widevine
CDM hint seeding runs on Linux when a sideloaded CDM is present.

---

## CLI

```bash
cloakbrowser install          # download free (or Pro) binary
cloakbrowser info --quick    # diagnostics without launch
cloakbrowser info --json
cloakbrowser update
cloakbrowser clear-cache
```

---

## Environment variables

| Variable | Purpose |
| --- | --- |
| `CLOAKBROWSER_CACHE_DIR` | Binary cache root (default `~/.cloakbrowser`) |
| `CLOAKBROWSER_BINARY_PATH` | Skip download; use a local Chromium |
| `CLOAKBROWSER_LICENSE_KEY` | Pro license |
| `CLOAKBROWSER_VERSION` | Pin a Chromium version |
| `CLOAKBROWSER_DOWNLOAD_URL` | Custom download mirror |
| `CLOAKBROWSER_SKIP_CHECKSUM` | Only for custom mirrors |
| `CLOAKBROWSER_AUTO_UPDATE` | Set `false` to freeze auto-update |
| `CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS` | GeoIP resolution timeout |

---

## Building & testing

```bash
cd rust
cargo test -p cloakbrowser
cargo build -p cloakbrowser-cli
cargo run -p cloakbrowser-cli -- info --quick
```

Unit tests cover config, proxy resolution, checksum parsing, zip-slip guards,
and launch-arg composition without network or a browser.

---

## Mapping to the Python source

| Rust | Python |
| --- | --- |
| `config.rs` | `cloakbrowser/config.py` |
| `download.rs` | `cloakbrowser/download.py` |
| `license.rs` | `cloakbrowser/license.py` |
| `geoip.rs` | `cloakbrowser/geoip.py` |
| `proxy.rs` | `_resolve_proxy_config` et al. in `browser.py` |
| `launch.rs` | `launch` / `build_args` in `browser.py` |
| `human/*` | `cloakbrowser/human/*` |
| `widevine.rs` | `cloakbrowser/widevine.py` |
| `launch_persistent_context` | `launch_persistent_context` in `browser.py` |
| `cloakbrowser-cli` | `cloakbrowser/__main__.py` |

Parity targets match the .NET client in `dotnet/` (same version pins, same
signing keys, same stealth flags).

---

## License

MIT for this wrapper (see repo root `LICENSE`). The patched Chromium binary is
subject to `BINARY-LICENSE.md`.
