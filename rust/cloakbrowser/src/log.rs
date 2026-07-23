//! Logging facade used across the library.
//!
//! By default only Info/Warning/Error go to stderr. Set `MinLevel` via
//! [`set_min_level`] or enable `tracing` subscribers for structured logs.

use std::sync::atomic::{AtomicU8, Ordering};

/// Log severity levels for CloakBrowser.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum Level {
    Debug = 0,
    Info = 1,
    Warning = 2,
    Error = 3,
    None = 4,
}

static MIN_LEVEL: AtomicU8 = AtomicU8::new(Level::Info as u8);

/// Minimum level that will be emitted. Defaults to Info.
pub fn set_min_level(level: Level) {
    MIN_LEVEL.store(level as u8, Ordering::Relaxed);
}

/// Current minimum log level.
pub fn min_level() -> Level {
    match MIN_LEVEL.load(Ordering::Relaxed) {
        0 => Level::Debug,
        1 => Level::Info,
        2 => Level::Warning,
        3 => Level::Error,
        _ => Level::None,
    }
}

fn emit(level: Level, message: &str) {
    if level < min_level() {
        return;
    }
    let tag = match level {
        Level::Debug => "debug",
        Level::Info => "info",
        Level::Warning => "warning",
        Level::Error => "error",
        Level::None => return,
    };
    eprintln!("[cloakbrowser:{tag}] {message}");

    match level {
        Level::Debug => tracing::debug!("{message}"),
        Level::Info => tracing::info!("{message}"),
        Level::Warning => tracing::warn!("{message}"),
        Level::Error => tracing::error!("{message}"),
        Level::None => {}
    }
}

pub fn debug(message: impl AsRef<str>) {
    emit(Level::Debug, message.as_ref());
}

pub fn info(message: impl AsRef<str>) {
    emit(Level::Info, message.as_ref());
}

pub fn warning(message: impl AsRef<str>) {
    emit(Level::Warning, message.as_ref());
}

pub fn error(message: impl AsRef<str>) {
    emit(Level::Error, message.as_ref());
}
