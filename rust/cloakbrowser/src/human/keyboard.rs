//! Human-like keyboard input.
//! Direct port of Python `cloakbrowser/human/keyboard.py` / .NET `HumanKeyboard.cs`.

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use playwright_rs::protocol::{CDPSession, Keyboard, Page};
use serde_json::json;

use super::config::{self, HumanConfig};
use crate::error::{Error, Result};
use crate::log;

fn shift_symbols() -> &'static HashSet<char> {
    static S: OnceLock<HashSet<char>> = OnceLock::new();
    S.get_or_init(|| "@#!$%^&*()_+{}|:\"<>?~".chars().collect())
}

fn nearby_keys() -> &'static HashMap<char, &'static str> {
    static M: OnceLock<HashMap<char, &'static str>> = OnceLock::new();
    M.get_or_init(|| {
        HashMap::from([
            ('a', "sqwz"),
            ('b', "vghn"),
            ('c', "xdfv"),
            ('d', "sfecx"),
            ('e', "wrsdf"),
            ('f', "dgrtcv"),
            ('g', "fhtyb"),
            ('h', "gjybn"),
            ('i', "ujko"),
            ('j', "hkunm"),
            ('k', "jloi"),
            ('l', "kop"),
            ('m', "njk"),
            ('n', "bhjm"),
            ('o', "iklp"),
            ('p', "ol"),
            ('q', "wa"),
            ('r', "edft"),
            ('s', "awedxz"),
            ('t', "rfgy"),
            ('u', "yhji"),
            ('v', "cfgb"),
            ('w', "qase"),
            ('x', "zsdc"),
            ('y', "tghu"),
            ('z', "asx"),
            ('1', "2q"),
            ('2', "13qw"),
            ('3', "24we"),
            ('4', "35er"),
            ('5', "46rt"),
            ('6', "57ty"),
            ('7', "68yu"),
            ('8', "79ui"),
            ('9', "80io"),
            ('0', "9p"),
        ])
    })
}

fn shift_symbol_codes() -> &'static HashMap<char, &'static str> {
    static M: OnceLock<HashMap<char, &'static str>> = OnceLock::new();
    M.get_or_init(|| {
        HashMap::from([
            ('!', "Digit1"),
            ('@', "Digit2"),
            ('#', "Digit3"),
            ('$', "Digit4"),
            ('%', "Digit5"),
            ('^', "Digit6"),
            ('&', "Digit7"),
            ('*', "Digit8"),
            ('(', "Digit9"),
            (')', "Digit0"),
            ('_', "Minus"),
            ('+', "Equal"),
            ('{', "BracketLeft"),
            ('}', "BracketRight"),
            ('|', "Backslash"),
            (':', "Semicolon"),
            ('"', "Quote"),
            ('<', "Comma"),
            ('>', "Period"),
            ('?', "Slash"),
            ('~', "Backquote"),
        ])
    })
}

fn shift_symbol_keycodes() -> &'static HashMap<char, i32> {
    static M: OnceLock<HashMap<char, i32>> = OnceLock::new();
    M.get_or_init(|| {
        HashMap::from([
            ('!', 49),
            ('@', 50),
            ('#', 51),
            ('$', 52),
            ('%', 53),
            ('^', 54),
            ('&', 55),
            ('*', 56),
            ('(', 57),
            (')', 48),
            ('_', 189),
            ('+', 187),
            ('{', 219),
            ('}', 221),
            ('|', 220),
            (':', 186),
            ('"', 222),
            ('<', 188),
            ('>', 190),
            ('?', 191),
            ('~', 192),
        ])
    })
}

fn is_ascii(c: char) -> bool {
    c as u32 <= 0x7F
}

fn get_nearby_key(ch: char) -> char {
    let lower = ch.to_ascii_lowercase();
    if let Some(neighbors) = nearby_keys().get(&lower) {
        if !neighbors.is_empty() {
            let idx = (rand::random::<u32>() as usize) % neighbors.len();
            let wrong = neighbors.chars().nth(idx).unwrap_or(ch);
            return if ch.is_ascii_uppercase() {
                wrong.to_ascii_uppercase()
            } else {
                wrong
            };
        }
    }
    ch
}

/// Type `text` with human-like per-character timing.
///
/// When `cdp` is provided, shift symbols use CDP `Input.dispatchKeyEvent`
/// (`isTrusted=true`). Otherwise falls back to `insert_text` + evaluate.
pub async fn human_type(
    page: &Page,
    keyboard: &Keyboard,
    text: &str,
    cfg: &HumanConfig,
    cdp: Option<&CDPSession>,
) -> Result<()> {
    let chars: Vec<char> = text.chars().collect();
    for (i, &ch) in chars.iter().enumerate() {
        // Non-ASCII — insertText
        if !is_ascii(ch) {
            config::sleep_ms(config::rand_range(cfg.key_hold)).await;
            keyboard
                .insert_text(&ch.to_string())
                .await
                .map_err(|e| Error::Playwright(e.to_string()))?;
            if i + 1 < chars.len() {
                inter_char_delay(cfg).await;
            }
            continue;
        }

        // Mistype chance — ASCII alphanumeric only
        if config::chance(cfg.mistype_chance) && ch.is_ascii_alphanumeric() {
            let wrong = get_nearby_key(ch);
            type_normal_char(keyboard, wrong, cfg).await?;
            config::sleep_ms(config::rand_range(cfg.mistype_delay_notice)).await;
            keyboard
                .down("Backspace")
                .await
                .map_err(|e| Error::Playwright(e.to_string()))?;
            config::sleep_ms(config::rand_range(cfg.key_hold)).await;
            keyboard
                .up("Backspace")
                .await
                .map_err(|e| Error::Playwright(e.to_string()))?;
            config::sleep_ms(config::rand_range(cfg.mistype_delay_correct)).await;
        }

        if ch.is_ascii_uppercase() && ch.is_ascii_alphabetic() {
            type_shifted_char(keyboard, ch, cfg).await?;
        } else if shift_symbols().contains(&ch) {
            type_shift_symbol(page, keyboard, ch, cfg, cdp).await?;
        } else {
            type_normal_char(keyboard, ch, cfg).await?;
        }

        if i + 1 < chars.len() {
            inter_char_delay(cfg).await;
        }
    }
    Ok(())
}

async fn type_normal_char(keyboard: &Keyboard, ch: char, cfg: &HumanConfig) -> Result<()> {
    let key = ch.to_string();
    keyboard
        .down(&key)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    config::sleep_ms(config::rand_range(cfg.key_hold)).await;
    keyboard
        .up(&key)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    Ok(())
}

async fn type_shifted_char(keyboard: &Keyboard, ch: char, cfg: &HumanConfig) -> Result<()> {
    keyboard
        .down("Shift")
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    config::sleep_ms(config::rand_range(cfg.shift_down_delay)).await;
    let key = ch.to_string();
    keyboard
        .down(&key)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    config::sleep_ms(config::rand_range(cfg.key_hold)).await;
    keyboard
        .up(&key)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    config::sleep_ms(config::rand_range(cfg.shift_up_delay)).await;
    keyboard
        .up("Shift")
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;
    Ok(())
}

async fn type_shift_symbol(
    page: &Page,
    keyboard: &Keyboard,
    ch: char,
    cfg: &HumanConfig,
    cdp: Option<&CDPSession>,
) -> Result<()> {
    if let Some(cdp) = cdp {
        let code = shift_symbol_codes().get(&ch).copied().unwrap_or("");
        let key_code = shift_symbol_keycodes().get(&ch).copied().unwrap_or(0);

        keyboard
            .down("Shift")
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
        config::sleep_ms(config::rand_range(cfg.shift_down_delay)).await;

        let ch_s = ch.to_string();
        cdp.send(
            "Input.dispatchKeyEvent",
            Some(json!({
                "type": "keyDown",
                "modifiers": 8,
                "key": ch_s,
                "code": code,
                "windowsVirtualKeyCode": key_code,
                "text": ch_s,
                "unmodifiedText": ch_s,
            })),
        )
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;

        config::sleep_ms(config::rand_range(cfg.key_hold)).await;

        cdp.send(
            "Input.dispatchKeyEvent",
            Some(json!({
                "type": "keyUp",
                "modifiers": 8,
                "key": ch_s,
                "code": code,
                "windowsVirtualKeyCode": key_code,
            })),
        )
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;

        config::sleep_ms(config::rand_range(cfg.shift_up_delay)).await;
        keyboard
            .up("Shift")
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
    } else {
        // Fallback — detectable but functional.
        log::debug("shift-symbol typed without CDP (fallback path)");
        keyboard
            .down("Shift")
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
        config::sleep_ms(config::rand_range(cfg.shift_down_delay)).await;
        keyboard
            .insert_text(&ch.to_string())
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
        let _ = page
            .evaluate_expression(
                &format!(
                    r#"(() => {{
                        const el = document.activeElement;
                        if (el) {{
                            el.dispatchEvent(new KeyboardEvent('keydown', {{ key: {}, bubbles: true }}));
                            el.dispatchEvent(new KeyboardEvent('keyup', {{ key: {}, bubbles: true }}));
                        }}
                    }})()"#,
                    serde_json::to_string(&ch.to_string()).unwrap_or_else(|_| "\"\"".into()),
                    serde_json::to_string(&ch.to_string()).unwrap_or_else(|_| "\"\"".into()),
                ),
            )
            .await;
        config::sleep_ms(config::rand_range(cfg.shift_up_delay)).await;
        keyboard
            .up("Shift")
            .await
            .map_err(|e| Error::Playwright(e.to_string()))?;
    }
    Ok(())
}

async fn inter_char_delay(cfg: &HumanConfig) {
    if config::chance(cfg.typing_pause_chance) {
        config::sleep_ms(config::rand_range(cfg.typing_pause_range)).await;
    } else {
        let delay =
            cfg.typing_delay + (rand::random::<f64>() - 0.5) * 2.0 * cfg.typing_delay_spread;
        config::sleep_ms(delay.max(10.0)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nearby_produces_neighbor() {
        for _ in 0..20 {
            let n = get_nearby_key('a');
            assert!(nearby_keys()[&'a'].contains(n) || n == 'a');
        }
    }

    #[test]
    fn shift_set_contains_at() {
        assert!(shift_symbols().contains(&'@'));
        assert!(!shift_symbols().contains(&'a'));
    }
}
