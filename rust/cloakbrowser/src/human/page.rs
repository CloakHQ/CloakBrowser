//! HumanPage — explicit humanized action API over a Playwright Page.
//!
//! Rust (like .NET) cannot monkey-patch Playwright's `Page`. Use this wrapper
//! for humanized click/fill/type/hover/scroll; access the raw page via
//! [`HumanPage::page`] for everything else.
//!
//! Behavioral port of .NET `HumanPage` / Python `patch_page` flows.

use playwright_rs::protocol::{CDPSession, Page};

use super::config::{self, HumanConfig};
use super::keyboard;
use super::mouse::{self, BoundingBox};
use super::scroll;
use crate::error::{Error, Result};
use crate::log;

/// Options accepted by humanized action methods.
#[derive(Debug, Clone)]
pub struct HumanActionOptions {
    /// Overall timeout in milliseconds (default 30000).
    pub timeout: f64,
    /// Skip motion guarantees / soft checks when true.
    pub force: bool,
}

impl Default for HumanActionOptions {
    fn default() -> Self {
        Self {
            timeout: 30000.0,
            force: false,
        }
    }
}

impl HumanActionOptions {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn timeout(mut self, ms: f64) -> Self {
        self.timeout = ms;
        self
    }

    pub fn force(mut self, v: bool) -> Self {
        self.force = v;
        self
    }
}

/// Cursor state tracked across humanized actions.
#[derive(Debug, Clone)]
struct CursorState {
    x: f64,
    y: f64,
    initialized: bool,
}

/// A human-like wrapper around a Playwright [`Page`].
pub struct HumanPage {
    page: Page,
    cfg: HumanConfig,
    cursor: CursorState,
    cdp: Option<CDPSession>,
}

impl HumanPage {
    /// Create a humanized page (initializes CDP stealth path + cursor when possible).
    pub async fn create(page: Page, cfg: HumanConfig) -> Result<Self> {
        let cdp = match page.context() {
            Ok(ctx) => match ctx.new_cdp_session(&page).await {
                Ok(s) => Some(s),
                Err(e) => {
                    log::debug(format!(
                        "Could not create CDP session - stealth keyboard disabled: {e}"
                    ));
                    None
                }
            },
            Err(e) => {
                log::debug(format!("Could not get page context for CDP: {e}"));
                None
            }
        };

        let mut hp = Self {
            page,
            cfg,
            cursor: CursorState {
                x: 0.0,
                y: 0.0,
                initialized: false,
            },
            cdp,
        };
        hp.init_cursor().await?;
        Ok(hp)
    }

    /// Create with the default humanize config.
    pub async fn create_default(page: Page) -> Result<Self> {
        Self::create(page, HumanConfig::default()).await
    }

    /// The underlying real Playwright page.
    pub fn page(&self) -> &Page {
        &self.page
    }

    /// Mutable access to the underlying page.
    pub fn page_mut(&mut self) -> &mut Page {
        &mut self.page
    }

    /// The resolved behavior configuration.
    pub fn config(&self) -> &HumanConfig {
        &self.cfg
    }

    /// Current virtual cursor position `(x, y)`.
    pub fn cursor(&self) -> (f64, f64) {
        (self.cursor.x, self.cursor.y)
    }

    async fn init_cursor(&mut self) -> Result<()> {
        self.cursor.x = config::rand_range(self.cfg.initial_cursor_x);
        self.cursor.y = config::rand_range(self.cfg.initial_cursor_y);
        let mouse = self.page.mouse();
        // Best-effort — viewport may not be ready.
        if mouse
            .move_to(
                self.cursor.x.round() as i32,
                self.cursor.y.round() as i32,
                None,
            )
            .await
            .is_ok()
        {
            self.cursor.initialized = true;
        }
        Ok(())
    }

    async fn ensure_cursor(&mut self) -> Result<()> {
        if !self.cursor.initialized {
            self.init_cursor().await?;
        }
        Ok(())
    }

    async fn maybe_idle(&mut self) -> Result<()> {
        if self.cfg.idle_between_actions {
            let secs = config::rand(
                self.cfg.idle_between_duration.min,
                self.cfg.idle_between_duration.max,
            );
            let mouse = self.page.mouse();
            let (x, y) = mouse::human_idle(
                &mouse,
                secs,
                self.cursor.x,
                self.cursor.y,
                &self.cfg,
            )
            .await?;
            self.cursor.x = x;
            self.cursor.y = y;
        }
        Ok(())
    }

    async fn get_box(&self, selector: &str) -> Result<Option<BoundingBox>> {
        scroll::get_element_box(&self.page, selector).await
    }

    async fn wait_for_box(&self, selector: &str, timeout_ms: f64) -> Result<BoundingBox> {
        let deadline = std::time::Instant::now()
            + std::time::Duration::from_millis(timeout_ms.max(1.0) as u64);
        loop {
            if let Some(b) = self.get_box(selector).await? {
                return Ok(b);
            }
            if std::time::Instant::now() >= deadline {
                return Err(Error::msg(format!(
                    "Timeout {timeout_ms}ms waiting for element: {selector}"
                )));
            }
            config::sleep_ms(50.0).await;
        }
    }

    async fn is_input_element(&self, selector: &str) -> bool {
        let sel_json = serde_json::to_string(selector).unwrap_or_else(|_| "\"\"".into());
        let expr = format!(
            r#"(() => {{
                const el = document.querySelector({sel_json});
                if (!el) return 'false';
                const tag = el.tagName.toLowerCase();
                return (tag === 'input' || tag === 'textarea'
                    || el.getAttribute('contenteditable') === 'true') ? 'true' : 'false';
            }})()"#
        );
        match self.page.evaluate_value(&expr).await {
            Ok(v) => v.contains("true"),
            Err(_) => false,
        }
    }

    /// Navigate and keep the humanize session (CDP may need re-bind after nav).
    pub async fn goto(&mut self, url: &str) -> Result<()> {
        self.page
            .goto(url, None)
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
        // Re-init CDP after navigation (session can go stale).
        self.cdp = match self.page.context() {
            Ok(ctx) => ctx.new_cdp_session(&self.page).await.ok(),
            Err(_) => None,
        };
        self.cursor.initialized = false;
        self.ensure_cursor().await?;
        Ok(())
    }

    /// Human-like click on `selector`.
    pub async fn click(&mut self, selector: &str) -> Result<()> {
        self.click_with(selector, HumanActionOptions::default()).await
    }

    /// Human-like click with options.
    pub async fn click_with(
        &mut self,
        selector: &str,
        options: HumanActionOptions,
    ) -> Result<()> {
        self.ensure_cursor().await?;
        self.maybe_idle().await?;

        if !options.force {
            let _ = self.wait_for_box(selector, options.timeout).await?;
        }

        let mouse = self.page.mouse();
        let sel = selector.to_string();
        let page = self.page.clone();
        let scroll = scroll::human_scroll_into_view(
            &self.page,
            &mouse,
            || {
                let page = page.clone();
                let sel = sel.clone();
                async move { scroll::get_element_box(&page, &sel).await }
            },
            self.cursor.x,
            self.cursor.y,
            &self.cfg,
        )
        .await?;
        self.cursor.x = scroll.cursor_x;
        self.cursor.y = scroll.cursor_y;
        let mut box_ = scroll.box_;

        if !options.force && scroll.did_scroll {
            config::sleep_ms(config::rand(50.0, 120.0)).await;
            if let Some(b) = self.get_box(selector).await? {
                box_ = b;
            }
        }

        let is_input = self.is_input_element(selector).await;
        let target = mouse::click_target(box_, is_input, &self.cfg);
        let mouse = self.page.mouse();
        mouse::human_move(
            &mouse,
            self.cursor.x,
            self.cursor.y,
            target.x,
            target.y,
            &self.cfg,
        )
        .await?;
        self.cursor.x = target.x;
        self.cursor.y = target.y;
        mouse::human_click(&mouse, is_input, &self.cfg).await?;
        Ok(())
    }

    /// Human-like hover over `selector`.
    pub async fn hover(&mut self, selector: &str) -> Result<()> {
        self.hover_with(selector, HumanActionOptions::default()).await
    }

    /// Human-like hover with options.
    pub async fn hover_with(
        &mut self,
        selector: &str,
        options: HumanActionOptions,
    ) -> Result<()> {
        self.ensure_cursor().await?;
        self.maybe_idle().await?;

        if !options.force {
            let _ = self.wait_for_box(selector, options.timeout).await?;
        }

        let mouse = self.page.mouse();
        let sel = selector.to_string();
        let page = self.page.clone();
        let scroll = scroll::human_scroll_into_view(
            &self.page,
            &mouse,
            || {
                let page = page.clone();
                let sel = sel.clone();
                async move { scroll::get_element_box(&page, &sel).await }
            },
            self.cursor.x,
            self.cursor.y,
            &self.cfg,
        )
        .await?;
        self.cursor.x = scroll.cursor_x;
        self.cursor.y = scroll.cursor_y;
        let mut box_ = scroll.box_;

        if !options.force && scroll.did_scroll {
            if let Some(b) = self.get_box(selector).await? {
                box_ = b;
            }
        }

        let target = mouse::click_target(box_, false, &self.cfg);
        let mouse = self.page.mouse();
        mouse::human_move(
            &mouse,
            self.cursor.x,
            self.cursor.y,
            target.x,
            target.y,
            &self.cfg,
        )
        .await?;
        self.cursor.x = target.x;
        self.cursor.y = target.y;
        Ok(())
    }

    /// Human-like typing into `selector` (appends to existing value).
    pub async fn type_text(&mut self, selector: &str, text: &str) -> Result<()> {
        self.type_text_with(selector, text, HumanActionOptions::default())
            .await
    }

    /// Human-like type with options.
    pub async fn type_text_with(
        &mut self,
        selector: &str,
        text: &str,
        options: HumanActionOptions,
    ) -> Result<()> {
        if !options.force {
            let _ = self.wait_for_box(selector, options.timeout).await?;
        }
        config::sleep_ms(config::rand_range(self.cfg.field_switch_delay)).await;
        self.click_with(
            selector,
            HumanActionOptions {
                timeout: options.timeout,
                force: options.force,
            },
        )
        .await?;
        config::sleep_ms(config::rand(100.0, 250.0)).await;

        let keyboard = self.page.keyboard();
        keyboard::human_type(
            &self.page,
            &keyboard,
            text,
            &self.cfg,
            self.cdp.as_ref(),
        )
        .await?;
        Ok(())
    }

    /// Human-like fill of `selector` (select-all, delete, then type).
    pub async fn fill(&mut self, selector: &str, value: &str) -> Result<()> {
        self.fill_with(selector, value, HumanActionOptions::default())
            .await
    }

    /// Human-like fill with options.
    pub async fn fill_with(
        &mut self,
        selector: &str,
        value: &str,
        options: HumanActionOptions,
    ) -> Result<()> {
        if !options.force {
            let _ = self.wait_for_box(selector, options.timeout).await?;
        }
        config::sleep_ms(config::rand_range(self.cfg.field_switch_delay)).await;
        self.click_with(
            selector,
            HumanActionOptions {
                timeout: options.timeout,
                force: options.force,
            },
        )
        .await?;
        config::sleep_ms(config::rand(100.0, 250.0)).await;

        let keyboard = self.page.keyboard();
        let select_all = if cfg!(target_os = "macos") {
            "Meta+a"
        } else {
            "Control+a"
        };
        keyboard
            .press(select_all, None)
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
        config::sleep_ms(config::rand(30.0, 80.0)).await;
        keyboard
            .press("Backspace", None)
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
        config::sleep_ms(config::rand(50.0, 150.0)).await;

        keyboard::human_type(
            &self.page,
            &keyboard,
            value,
            &self.cfg,
            self.cdp.as_ref(),
        )
        .await?;
        Ok(())
    }

    /// Human-like scroll until `selector` is in the target viewport zone.
    pub async fn scroll_to(&mut self, selector: &str) -> Result<()> {
        self.ensure_cursor().await?;
        let mouse = self.page.mouse();
        let result = scroll::scroll_to_element(
            &self.page,
            &mouse,
            selector,
            self.cursor.x,
            self.cursor.y,
            &self.cfg,
        )
        .await?;
        self.cursor.x = result.cursor_x;
        self.cursor.y = result.cursor_y;
        Ok(())
    }

    /// Move the humanized cursor to absolute coordinates (Bezier path).
    pub async fn move_to(&mut self, x: f64, y: f64) -> Result<()> {
        self.ensure_cursor().await?;
        let mouse = self.page.mouse();
        mouse::human_move(&mouse, self.cursor.x, self.cursor.y, x, y, &self.cfg).await?;
        self.cursor.x = x;
        self.cursor.y = y;
        Ok(())
    }
}
