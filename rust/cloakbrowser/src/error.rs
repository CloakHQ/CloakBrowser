//! Error types for CloakBrowser.

use thiserror::Error;

/// Library-wide error type.
#[derive(Debug, Error)]
pub enum Error {
    #[error("{0}")]
    Message(String),

    #[error("unsupported platform: {0}")]
    UnsupportedPlatform(String),

    #[error("invalid browser version pin: {0}")]
    InvalidVersion(String),

    #[error("binary not found: {0}")]
    BinaryNotFound(String),

    /// A downloaded binary could not be authenticated (bad/missing signature,
    /// version mismatch, or checksum failure).
    ///
    /// Distinct from transient download/network errors: a verification failure is
    /// a tampering signal and MUST surface, never silently fall back to another
    /// binary.
    #[error("binary verification failed: {0}")]
    BinaryVerification(String),

    #[error("pro binary unavailable: {0}")]
    ProUnavailable(String),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("http error: {0}")]
    Http(#[from] reqwest::Error),

    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("playwright error: {0}")]
    Playwright(String),

    #[error(transparent)]
    Other(#[from] anyhow::Error),
}

impl Error {
    pub fn msg(s: impl Into<String>) -> Self {
        Self::Message(s.into())
    }
}

/// Result alias for this crate.
pub type Result<T> = std::result::Result<T, Error>;
