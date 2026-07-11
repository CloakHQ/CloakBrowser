//! Human-like mouse movement and clicking.
//! Direct port of Python `cloakbrowser/human/mouse.py` / .NET `HumanMouse.cs`.

use super::config::{self, HumanConfig};
use crate::error::{Error, Result};
use playwright_rs::protocol::Mouse;

/// A 2D point used by the mouse-movement curve math.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    pub x: f64,
    pub y: f64,
}

impl Point {
    pub fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }
}

/// Element bounding box in CSS pixels.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BoundingBox {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// Cubic ease-in-out, matching the Python implementation.
pub fn ease_in_out(t: f64) -> f64 {
    if t < 0.5 {
        4.0 * t * t * t
    } else {
        1.0 - (-2.0 * t + 2.0).powi(3) / 2.0
    }
}

/// Cubic Bezier interpolation between four control points.
pub fn bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: f64) -> Point {
    let u = 1.0 - t;
    let uu = u * u;
    let uuu = uu * u;
    let tt = t * t;
    let ttt = tt * t;
    Point {
        x: uuu * p0.x + 3.0 * uu * t * p1.x + 3.0 * u * tt * p2.x + ttt * p3.x,
        y: uuu * p0.y + 3.0 * uu * t * p1.y + 3.0 * u * tt * p2.y + ttt * p3.y,
    }
}

fn random_control_points(start: Point, end: Point) -> (Point, Point) {
    let dx = end.x - start.x;
    let dy = end.y - start.y;
    let mut dist = (dx * dx + dy * dy).sqrt();
    if dist == 0.0 {
        dist = 1.0;
    }
    let px = -dy / dist;
    let py = dx / dist;
    let bias1 = config::rand(-0.3, 0.3) * dist;
    let bias2 = config::rand(-0.3, 0.3) * dist;
    (
        Point::new(
            start.x + dx * 0.25 + px * bias1,
            start.y + dy * 0.25 + py * bias1,
        ),
        Point::new(
            start.x + dx * 0.75 + px * bias2,
            start.y + dy * 0.75 + py * bias2,
        ),
    )
}

async fn move_xy(mouse: &Mouse, x: f64, y: f64) -> Result<()> {
    mouse
        .move_to(x.round() as i32, y.round() as i32, None)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))
}

/// Move the cursor along a human-like Bezier curve with wobble, burst pauses,
/// and an optional overshoot.
pub async fn human_move(
    mouse: &Mouse,
    start_x: f64,
    start_y: f64,
    end_x: f64,
    end_y: f64,
    cfg: &HumanConfig,
) -> Result<()> {
    let dist = ((end_x - start_x).powi(2) + (end_y - start_y).powi(2)).sqrt();
    if dist < 1.0 {
        return Ok(());
    }

    let steps = (dist / cfg.mouse_steps_divisor)
        .round()
        .clamp(cfg.mouse_min_steps as f64, cfg.mouse_max_steps as f64) as i32;
    let start = Point::new(start_x, start_y);
    let end = Point::new(end_x, end_y);
    let (cp1, cp2) = random_control_points(start, end);

    let mut burst_counter = 0;
    let burst_size = config::rand_int_range(cfg.mouse_burst_size);

    for i in 0..=steps {
        let progress = i as f64 / steps as f64;
        let eased_t = ease_in_out(progress);
        let pt = bezier(start, cp1, cp2, end, eased_t);

        let wobble_amp = (std::f64::consts::PI * progress).sin() * cfg.mouse_wobble_max;
        let wx = pt.x + (rand::random::<f64>() - 0.5) * 2.0 * wobble_amp;
        let wy = pt.y + (rand::random::<f64>() - 0.5) * 2.0 * wobble_amp;

        move_xy(mouse, wx, wy).await?;

        burst_counter += 1;
        if burst_counter >= burst_size && i < steps {
            config::sleep_ms(config::rand_range(cfg.mouse_burst_pause)).await;
            burst_counter = 0;
        }
    }

    if config::chance(cfg.mouse_overshoot_chance) {
        let overshoot_dist = config::rand_range(cfg.mouse_overshoot_px);
        let angle = (end_y - start_y).atan2(end_x - start_x);
        move_xy(
            mouse,
            end_x + angle.cos() * overshoot_dist,
            end_y + angle.sin() * overshoot_dist,
        )
        .await?;
        config::sleep_ms(config::rand(30.0, 70.0)).await;
        move_xy(
            mouse,
            end_x + (rand::random::<f64>() - 0.5) * 4.0,
            end_y + (rand::random::<f64>() - 0.5) * 4.0,
        )
        .await?;
    }

    Ok(())
}

/// Compute a randomized click point inside a bounding box.
pub fn click_target(box_: BoundingBox, is_input: bool, cfg: &HumanConfig) -> Point {
    let (x_frac, y_frac) = if is_input {
        (
            config::rand_range(cfg.click_input_x_range),
            config::rand(0.30, 0.70),
        )
    } else {
        (config::rand(0.35, 0.65), config::rand(0.35, 0.65))
    };
    Point::new(
        (box_.x + box_.width * x_frac).round(),
        (box_.y + box_.height * y_frac).round(),
    )
}

/// Perform a human-like press: aim delay, mouse down, hold, mouse up.
pub async fn human_click(mouse: &Mouse, is_input: bool, cfg: &HumanConfig) -> Result<()> {
    let aim_delay = if is_input {
        config::rand_range(cfg.click_aim_delay_input)
    } else {
        config::rand_range(cfg.click_aim_delay_button)
    };
    config::sleep_ms(aim_delay).await;

    let hold_time = if is_input {
        config::rand_range(cfg.click_hold_input)
    } else {
        config::rand_range(cfg.click_hold_button)
    };

    mouse
        .down(None)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    config::sleep_ms(hold_time).await;
    mouse
        .up(None)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    Ok(())
}

/// Drift the cursor with tiny random movements for ~`seconds` seconds.
pub async fn human_idle(
    mouse: &Mouse,
    seconds: f64,
    mut cx: f64,
    mut cy: f64,
    cfg: &HumanConfig,
) -> Result<(f64, f64)> {
    let end = std::time::Instant::now() + std::time::Duration::from_secs_f64(seconds);
    while std::time::Instant::now() < end {
        cx += (rand::random::<f64>() - 0.5) * 2.0 * cfg.idle_drift_px;
        cy += (rand::random::<f64>() - 0.5) * 2.0 * cfg.idle_drift_px;
        move_xy(mouse, cx, cy).await?;
        config::sleep_ms(config::rand_range(cfg.idle_pause_range)).await;
    }
    Ok((cx, cy))
}

/// Wheel helper used by scroll (and direct wheel humanization).
pub async fn wheel(mouse: &Mouse, delta_x: i32, delta_y: i32) -> Result<()> {
    mouse
        .wheel(delta_x, delta_y)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ease_endpoints() {
        assert!((ease_in_out(0.0) - 0.0).abs() < 1e-9);
        assert!((ease_in_out(1.0) - 1.0).abs() < 1e-9);
        assert!(ease_in_out(0.5) > 0.4 && ease_in_out(0.5) < 0.6);
    }

    #[test]
    fn bezier_endpoints() {
        let p0 = Point::new(0.0, 0.0);
        let p1 = Point::new(10.0, 20.0);
        let p2 = Point::new(30.0, 40.0);
        let p3 = Point::new(100.0, 50.0);
        let a = bezier(p0, p1, p2, p3, 0.0);
        let b = bezier(p0, p1, p2, p3, 1.0);
        assert!((a.x - 0.0).abs() < 1e-9 && (a.y - 0.0).abs() < 1e-9);
        assert!((b.x - 100.0).abs() < 1e-9 && (b.y - 50.0).abs() < 1e-9);
    }

    #[test]
    fn click_target_inside_box() {
        let cfg = HumanConfig::default();
        let box_ = BoundingBox {
            x: 100.0,
            y: 200.0,
            width: 80.0,
            height: 40.0,
        };
        for _ in 0..20 {
            let p = click_target(box_, false, &cfg);
            assert!(p.x >= box_.x && p.x <= box_.x + box_.width);
            assert!(p.y >= box_.y && p.y <= box_.y + box_.height);
        }
    }
}
