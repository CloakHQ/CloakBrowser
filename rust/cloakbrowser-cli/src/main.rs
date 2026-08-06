//! CLI for cloakbrowser — download and manage the stealth Chromium binary.
//! Direct port of Python `cloakbrowser/__main__.py` / .NET `CloakBrowser.Cli`.
//!
//! Usage:
//!   cloakbrowser install      # Download binary (with progress)
//!   cloakbrowser info         # Environment + binary diagnostics (--quick, --json)
//!   cloakbrowser doctor       # Alias for info
//!   cloakbrowser update       # Check for and download newer binary
//!   cloakbrowser clear-cache  # Remove cached binaries

use clap::{Parser, Subcommand};
use cloakbrowser::log::{self, Level};

const UPGRADE_HINT: &str =
    "→ Try the latest Pro binary (Chromium 148) free for 7 days: https://cloakbrowser.dev";

#[derive(Parser)]
#[command(
    name = "cloakbrowser",
    about = "CloakBrowser — stealth Chromium binary manager",
    version = cloakbrowser::VERSION
)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Subcommand)]
enum Commands {
    /// Download the stealth Chromium binary
    Install,
    /// Environment + binary diagnostics
    Info {
        /// Skip launch probe
        #[arg(long)]
        quick: bool,
        /// Alias for --quick
        #[arg(long = "no-launch")]
        no_launch: bool,
        /// Emit JSON
        #[arg(long)]
        json: bool,
    },
    /// Alias for info
    Doctor {
        #[arg(long)]
        quick: bool,
        #[arg(long = "no-launch")]
        no_launch: bool,
        #[arg(long)]
        json: bool,
    },
    /// Check for and download a newer binary
    Update,
    /// Remove cached binaries
    #[command(name = "clear-cache")]
    ClearCache,
}

#[tokio::main]
async fn main() {
    log::set_min_level(Level::Info);

    let cli = Cli::parse();
    let code = match run(cli).await {
        Ok(()) => 0,
        Err(e) => {
            eprintln!("Error: {e}");
            1
        }
    };
    std::process::exit(code);
}

async fn run(cli: Cli) -> anyhow::Result<()> {
    match cli.command {
        None => {
            print_help();
            anyhow::bail!("no command");
        }
        Some(Commands::Install) => {
            let path = cloakbrowser::ensure_binary(None, None).await?;
            println!("{}", path.display());
            eprintln!("{UPGRADE_HINT}");
        }
        Some(Commands::Info {
            quick,
            no_launch,
            json,
        })
        | Some(Commands::Doctor {
            quick,
            no_launch,
            json,
        }) => {
            cmd_info(quick || no_launch, json)?;
        }
        Some(Commands::Update) => {
            match cloakbrowser::check_for_update().await? {
                Some(v) => {
                    println!("Updated to Chromium {v}");
                    let info = cloakbrowser::binary_info(None)?;
                    println!("{}", info.binary_path);
                }
                None => {
                    let info = cloakbrowser::binary_info(None)?;
                    println!("Already up to date (Chromium {})", info.version);
                }
            }
        }
        Some(Commands::ClearCache) => {
            cloakbrowser::clear_cache()?;
            println!("Cache cleared.");
        }
    }
    Ok(())
}

fn cmd_info(quick: bool, as_json: bool) -> anyhow::Result<()> {
    let diag = cloakbrowser::diagnostics::collect(quick);
    if as_json {
        println!("{}", serde_json::to_string_pretty(&diag)?);
        return Ok(());
    }

    let env = diag.get("environment").and_then(|v| v.as_object());
    println!("CloakBrowser diagnostics");
    if let Some(env) = env {
        println!(
            "Rust:      {}",
            env.get("rust").and_then(|v| v.as_str()).unwrap_or("?")
        );
        println!(
            "OS:        {} {}",
            env.get("os").and_then(|v| v.as_str()).unwrap_or("?"),
            env.get("arch").and_then(|v| v.as_str()).unwrap_or("?")
        );
        println!(
            "Platform:  {}",
            env.get("platform_tag")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
        );
    }

    if let Some(binary) = diag.get("binary").and_then(|v| v.as_object()) {
        if let Some(err) = binary.get("error") {
            println!("Binary:    unavailable ({err})");
        } else {
            let tier = binary.get("tier").and_then(|v| v.as_str()).unwrap_or("?");
            if tier == "override" {
                println!("Version:   set via CLOAKBROWSER_BINARY_PATH (see Launch line)");
            } else if let Some(ver) = binary.get("version").and_then(|v| v.as_str()) {
                println!("Version:   {ver} ({tier})");
            }
            if let Some(path) = binary.get("path").and_then(|v| v.as_str()) {
                println!("Binary:    {path}");
            }
            if let Some(installed) = binary.get("installed") {
                println!("Installed: {installed}");
            }
            if let Some(cd) = binary.get("cache_dir").and_then(|v| v.as_str()) {
                if !cd.is_empty() {
                    println!("Cache:     {cd}");
                }
            }
            if let Some(ov) = binary.get("override").and_then(|v| v.as_str()) {
                println!("Override:  {ov} (CLOAKBROWSER_BINARY_PATH)");
            }
        }
    }

    if let Some(launch) = diag.get("launch").and_then(|v| v.as_object()) {
        if launch.get("tested").and_then(|v| v.as_bool()) != Some(true) {
            println!(
                "Launch:    {}",
                launch
                    .get("reason")
                    .and_then(|v| v.as_str())
                    .unwrap_or("skipped")
            );
        }
    }

    if let Some(lic) = diag.get("license").and_then(|v| v.as_object()) {
        let present = lic.get("present").and_then(|v| v.as_bool()).unwrap_or(false);
        println!(
            "License:   {}",
            if present {
                "present"
            } else {
                "none (free tier)"
            }
        );
    }

    eprintln!("\n{UPGRADE_HINT}");
    Ok(())
}

fn print_help() {
    eprintln!(
        "\
CloakBrowser — stealth Chromium binary manager

Usage:
  cloakbrowser install       Download binary
  cloakbrowser info          Environment + binary diagnostics
  cloakbrowser doctor        Alias for info
  cloakbrowser update        Check for and download newer binary
  cloakbrowser clear-cache   Remove cached binaries

Flags for info/doctor:
  --quick / --no-launch      Skip launch probe
  --json                     Emit JSON
"
    );
}
