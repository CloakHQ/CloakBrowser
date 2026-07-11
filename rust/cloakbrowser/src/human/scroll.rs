//! Human-like scrolling via mouse wheel events.
//! Direct port of Python `cloakbrowser/human/scroll.py` / .NET `HumanScroll.cs`.

use playwright_rs::protocol::{Mouse, Page};
use serde::Deserialize;

use super::config::{self, HumanConfig};
use super::mouse::{self, BoundingBox};
use crate::error::{Error, Result};

/// Result of a humanized scroll-into-view operation.
#[derive(Debug, Clone)]
pub struct ScrollResult {
    pub box_: BoundingBox,
    pub cursor_x: f64,
    pub cursor_y: f64,
    pub did_scroll: bool,
}

fn is_in_viewport(bounds: BoundingBox, viewport_height: f64, cfg: &HumanConfig) -> bool {
    let top_edge = bounds.y;
    let bottom_edge = bounds.y + bounds.height;
    let zone_top = viewport_height * cfg.scroll_target_zone.min;
    let zone_bottom = viewport_height * cfg.scroll_target_zone.max;
    top_edge >= zone_top && bottom_edge <= zone_bottom
}

/// Send one logical scroll as a burst of small wheel events.
async fn smooth_wheel(mouse: &Mouse, delta: i32, _cfg: &HumanConfig) -> Result<()> {
    let abs_d = delta.unsigned_abs() as f64;
    let sign = if delta > 0 { 1 } else { -1 };
    let mut sent = 0.0;
    while sent < abs_d {
        let step_size = config::rand(20.0, 40.0);
        let chunk = step_size.min(abs_d - sent);
        mouse::wheel(mouse, 0, (chunk.round() as i32) * sign).await?;
        sent += chunk;
        config::sleep_ms(config::rand(8.0, 20.0)).await;
    }
    Ok(())
}

#[derive(Deserialize)]
struct WindowSize {
    width: f64,
    height: f64,
}

async fn resolve_viewport(page: &Page) -> Result<(f64, f64)> {
    if let Some(vp) = page.viewport_size() {
        return Ok((vp.width as f64, vp.height as f64));
    }
    // Headed / no_viewport: live window dimensions.
    let raw = page
        .evaluate_value("() => JSON.stringify({ width: window.innerWidth, height: window.innerHeight })")
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    let size: WindowSize = serde_json::from_str(&raw)
        .map_err(|e| Error::msg(format!("Failed to parse viewport: {e}")))?;
    if size.height == 0.0 {
        return Err(Error::msg("Viewport size not available"));
    }
    Ok((size.width, size.height))
}

/// Humanized scroll-into-view using a box provider (selector or handle based).
pub async fn human_scroll_into_view<F, Fut>(
    page: &Page,
    mouse: &Mouse,
    mut get_box: F,
    mut cursor_x: f64,
    mut cursor_y: f64,
    cfg: &HumanConfig,
) -> Result<ScrollResult>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = Result<Option<BoundingBox>>>,
{
    let (viewport_width, viewport_height) = resolve_viewport(page).await?;

    let mut box_ = get_box()
        .await?
        .ok_or_else(|| Error::msg("Element not found while scrolling into view"))?;

    if is_in_viewport(box_, viewport_height, cfg) {
        return Ok(ScrollResult {
            box_,
            cursor_x,
            cursor_y,
            did_scroll: false,
        });
    }

    // Move cursor into scroll area.
    let scroll_area_x = (viewport_width * config::rand(0.3, 0.7)).round();
    let scroll_area_y = (viewport_height * config::rand(0.3, 0.7)).round();
    mouse::human_move(mouse, cursor_x, cursor_y, scroll_area_x, scroll_area_y, cfg).await?;
    cursor_x = scroll_area_x;
    cursor_y = scroll_area_y;
    config::sleep_ms(config::rand_range(cfg.scroll_pre_move_delay)).await;

    let target_y =
        viewport_height * config::rand(cfg.scroll_target_zone.min, cfg.scroll_target_zone.max);
    let element_center = box_.y + box_.height / 2.0;
    let distance_to_scroll = element_center - target_y;

    let direction = if distance_to_scroll > 0.0 { 1 } else { -1 };
    let abs_distance = distance_to_scroll.abs();
    let avg_delta = (cfg.scroll_delta_base.min + cfg.scroll_delta_base.max) / 2.0;
    let total_clicks = ((abs_distance / avg_delta).ceil() as i32).max(3);
    let accel_steps = config::rand_int_range(cfg.scroll_accel_steps);
    let decel_steps = config::rand_int_range(cfg.scroll_decel_steps);

    let mut scrolled = 0.0;
    for i in 0..total_clicks {
        let (delta, pause) = if i < accel_steps {
            (config::rand(80.0, 100.0), config::rand_range(cfg.scroll_pause_slow))
        } else if i >= total_clicks - decel_steps {
            (config::rand(60.0, 90.0), config::rand_range(cfg.scroll_pause_slow))
        } else {
            (
                config::rand_range(cfg.scroll_delta_base),
                config::rand_range(cfg.scroll_pause_fast),
            )
        };

        let delta = delta * (1.0 + (rand::random::<f64>() - 0.5) * 2.0 * cfg.scroll_delta_variance);
        let delta_int = (delta.round() as i32) * direction;

        smooth_wheel(mouse, delta_int, cfg).await?;
        scrolled += delta_int.unsigned_abs() as f64;
        config::sleep_ms(pause).await;

        if i % 3 == 2 || i == total_clicks - 1 {
            if let Some(b) = get_box().await? {
                box_ = b;
                if is_in_viewport(box_, viewport_height, cfg) {
                    break;
                }
            }
        }
        if scrolled >= abs_distance * 1.1 {
            break;
        }
    }

    // Optional overshoot + correction.
    if config::chance(cfg.scroll_overshoot_chance) {
        let overshoot_px =
            (config::rand_range(cfg.scroll_overshoot_px).round() as i32) * direction;
        smooth_wheel(mouse, overshoot_px, cfg).await?;
        config::sleep_ms(config::rand_range(cfg.scroll_settle_delay)).await;
        let corrections = config::rand_int_range(config::Range::new(1.0, 2.0));
        for _ in 0..corrections {
            let corr_delta = (config::rand(40.0, 80.0).round() as i32) * -direction;
            smooth_wheel(mouse, corr_delta, cfg).await?;
            config::sleep_ms(config::rand(100.0, 250.0)).await;
        }
    }

    config::sleep_ms(config::rand_range(cfg.scroll_settle_delay)).await;

    box_ = get_box()
        .await?
        .ok_or_else(|| Error::msg("Element lost after scrolling into view"))?;

    Ok(ScrollResult {
        box_,
        cursor_x,
        cursor_y,
        did_scroll: true,
    })
}

/// Selector-based humanized scroll.
pub async fn scroll_to_element(
    page: &Page,
    mouse: &Mouse,
    selector: &str,
    cursor_x: f64,
    cursor_y: f64,
    cfg: &HumanConfig,
) -> Result<ScrollResult> {
    let sel = selector.to_string();
    human_scroll_into_view(
        page,
        mouse,
        || {
            let page = page.clone();
            let sel = sel.clone();
            async move { get_element_box(&page, &sel).await }
        },
        cursor_x,
        cursor_y,
        cfg,
    )
    .await
}

/// Locate `selector` and return its bounding box.
pub async fn get_element_box(page: &Page, selector: &str) -> Result<Option<BoundingBox>> {
    let locator = page.locator(selector).await;
    match locator.bounding_box().await {
        Ok(Some(b)) => Ok(Some(BoundingBox {
            x: b.x,
            y: b.y,
            width: b.width,
            height: b.height,
        })),
        Ok(None) => Ok(None),
        Err(_) => Ok(None),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn viewport_zone_check() {
        let cfg = HumanConfig::default();
        let box_in = BoundingBox {
            x: 0.0,
            y: 300.0,
            width: 100.0,
            height: 40.0,
        };
        assert!(is_in_viewport(box_in, 1000.0, &cfg));
        let box_out = BoundingBox {
            x: 0.0,
            y: 10.0,
            width: 100.0,
            height: 40.0,
        };
        assert!(!is_in_viewport(box_out, 1000.0, &cfg));
    }
}
