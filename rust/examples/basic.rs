//! Basic CloakBrowser launch example.
//!
//! ```bash
//! cd rust && cargo run --example basic -p cloakbrowser
//! ```

use cloakbrowser::{launch, LaunchOptions};

#[tokio::main]
async fn main() -> cloakbrowser::Result<()> {
    let browser = launch(LaunchOptions {
        headless: true,
        ..Default::default()
    })
    .await?;

    let page = browser.new_page().await?;
    let _ = page.goto("https://example.com", None).await;
    let title = page.title().await.unwrap_or_default();
    println!("Title: {title}");

    browser.close().await?;
    Ok(())
}
