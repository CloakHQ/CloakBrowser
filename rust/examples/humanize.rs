//! Humanize demo — Bezier mouse + human typing.
//!
//! ```bash
//! cd rust && cargo run --example humanize -p cloakbrowser
//! ```

use cloakbrowser::{launch, LaunchOptions, HumanPreset};

#[tokio::main]
async fn main() -> cloakbrowser::Result<()> {
    let browser = launch(LaunchOptions {
        headless: true,
        humanize: true,
        human_preset: HumanPreset::Default,
        ..Default::default()
    })
    .await?;

    let mut page = browser.new_human_page().await?;
    page.goto("data:text/html,<html><body>\
        <h1>Hello</h1>\
        <input id='email' type='text' />\
        <button id='go'>Go</button>\
        </body></html>")
        .await?;

    page.fill("#email", "user@example.com").await?;
    page.click("#go").await?;

    println!("Cursor at: {:?}", page.cursor());
    println!("Done (humanized fill + click).");

    browser.close().await?;
    Ok(())
}
