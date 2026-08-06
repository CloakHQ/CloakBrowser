//! Persistent profile example — cookies/state survive across runs.
//!
//! ```bash
//! cd rust && cargo run --example persistent_context -p cloakbrowser
//! ```

use cloakbrowser::{launch_persistent_context, LaunchContextOptions};

#[tokio::main]
async fn main() -> cloakbrowser::Result<()> {
    let profile = std::env::temp_dir().join("cloakbrowser-rust-profile");
    println!("Profile dir: {}", profile.display());

    let ctx = launch_persistent_context(
        &profile,
        LaunchContextOptions {
            headless: true,
            ..Default::default()
        },
    )
    .await?;

    let page = ctx.new_page().await?;
    let _ = page
        .goto("https://example.com", None)
        .await;
    println!(
        "Title: {}",
        page.title().await.unwrap_or_default()
    );
    println!(
        "Profile will be reused next run at: {}",
        profile.display()
    );

    ctx.close().await?;
    Ok(())
}
