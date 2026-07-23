//! Human-like behavioral layer (mouse Bezier, typing, scroll).
//!
//! Direct port of Python `cloakbrowser/human/*` and .NET `CloakBrowser.Human/`.
//!
//! Rust cannot monkey-patch Playwright's sealed `Page` API the way Python/JS do.
//! Use [`HumanPage`] for humanized click/fill/type/hover — same approach as .NET's
//! explicit engine. When `humanize=true` at launch, prefer
//! [`crate::CloakBrowser::new_human_page`].
//!
//! # Example
//!
//! ```no_run
//! use cloakbrowser::{launch, LaunchOptions, human::{HumanPage, HumanConfig}};
//!
//! #[tokio::main]
//! async fn main() -> cloakbrowser::Result<()> {
//!     let browser = launch(LaunchOptions {
//!         humanize: true,
//!         ..Default::default()
//!     }).await?;
//!
//!     let mut page = browser.new_human_page().await?;
//!     page.goto("https://example.com").await?;
//!     page.click("a").await?;
//!     browser.close().await?;
//!     Ok(())
//! }
//! ```

pub mod config;
pub mod keyboard;
pub mod mouse;
pub mod page;
pub mod scroll;

pub use config::{HumanConfig, HumanPreset, Range};
pub use mouse::{BoundingBox, Point};
pub use page::{HumanActionOptions, HumanPage};
