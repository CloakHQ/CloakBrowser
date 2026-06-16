"""PerimeterX challenge detection logic.

Detects PerimeterX "Press & Hold" / "Pressione e segure" / "Activate and hold"
challenge UI in the current page, including iframe, shadow DOM, and modal variants.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .config import PX_TEXT_MARKERS

logger = logging.getLogger("cloakbrowser.pxbypass.detector")

# Regex for the hold button short text - supports multiple languages/wordings
_HOLD_BTN_RE = re.compile(
    r"^\s*(pressione e segure|press and hold|press & hold|activate and hold)\s*$",
    re.IGNORECASE,
)

# Probe JS that checks for PX challenge presence
_PROBE_PX_JS = """
() => {
  const results = {
    modalVisible: false,
    onIfoodApp: false,
    isCf: false,
    isBlockPage: false,
    url: window.location.href,
    title: document.title,
    main: { title: document.title, markersFound: [], bodyPreview: '' },
    pxGlobals: [],
    shadowHosts: [],
    pxIframes: [],
    diagnosis: 'unknown',
  };

  // Check URL for PX/CF patterns
  const host = window.location.hostname;
  const path = window.location.pathname;
  if (host.includes('px') || path.includes('px-captcha')) {
    results.isBlockPage = true;
  }

  // Check for common PX-related global objects
  const pxCandidates = ['_px', 'px_captcha', 'PX', 'PERIMETERX'];
  for (const key of pxCandidates) {
    if (key in window) results.pxGlobals.push(key);
  }

  // Check iframe-based PX modal in #px-captcha
  const pxCaptcha = document.getElementById('px-captcha');
  if (pxCaptcha) {
    results.modalVisible = true;
    const iframe = pxCaptcha.querySelector('iframe');
    if (iframe) {
      // Use getComputedStyle for cross-origin safety
      var style = window.getComputedStyle(iframe);
      results.pxIframes.push({
        display: style.display,
        width: iframe.offsetWidth,
        height: iframe.offsetHeight,
        token: iframe.getAttribute('token') ? 'present' : 'absent',
        visible: iframe.offsetWidth > 0 && iframe.offsetHeight > 0,
      });
    }
  }

  // Check #px-captcha-modal (iFood variant)
  const modal = document.getElementById('px-captcha-modal');
  if (modal && modal.contentDocument) {
    results.modalVisible = true;
  }

  // Check shadow DOM hosts that might contain PX
  const allElements = document.querySelectorAll('*');
  for (const el of allElements) {
    if (el.shadowRoot && el.shadowRoot.querySelector('#px-captcha')) {
      results.shadowHosts.push(el.tagName);
      results.modalVisible = true;
    }
  }

  // Check for px-cloud.net scripts (Walmart/cloud variant)
  const pxScripts = [];
  document.querySelectorAll('script').forEach(s => {
    if (s.src && s.src.includes('px-cloud.net')) {
      pxScripts.push(s.src.substring(0, 100));
    }
  });
  if (pxScripts.length > 0) {
    results.pxScripts = pxScripts;
    results.modalVisible = true;
  }

  // Body text markers
  const body = document.body ? (document.body.innerText || '') : '';
  results.main.bodyPreview = body.slice(0, 200);
  const markers = """ + str(list(PX_TEXT_MARKERS)) + """;
  for (const marker of markers) {
    if (body.toLowerCase().includes(marker)) {
      results.main.markersFound.push(marker);
      results.modalVisible = true;
    }
  }

  // Check for "Activate and hold" (Walmart variant)
  if (body.toLowerCase().includes('activate and hold')) {
    if (!results.main.markersFound.includes('activate and hold')) {
      results.main.markersFound.push('activate and hold');
      results.modalVisible = true;
    }
  }
  // Check for "Robot or human" (common PX block page title)
  if (body.toLowerCase().includes('robot or human')) {
    if (!results.main.markersFound.includes('robot or human')) {
      results.main.markersFound.push('robot or human');
      results.modalVisible = true;
    }
  }

  // Diagnosis
  if (results.modalVisible) {
    results.diagnosis = 'px_visible';
  } else if (results.pxGlobals.length > 0) {
    results.diagnosis = 'px_globals_found';
  } else {
    results.diagnosis = 'clean';
  }

  return results;
}
"""


def detect_px(page: Any) -> str | None:
    """Detect if the current page has a PerimeterX challenge.

    Args:
        page: Playwright Page object (sync or async).

    Returns:
        'perimeterx' if PX challenge is detected,
        None if no challenge is visible.
    """
    try:
        result = page.evaluate(_PROBE_PX_JS)
        if isinstance(result, dict):
            if result.get("modalVisible") or result.get("diagnosis") in (
                "px_visible", "px_globals_found",
            ):
                logger.debug(
                    "PX detected: diagnosis=%s, globals=%s, markers=%s, pxScripts=%s",
                    result.get("diagnosis"),
                    result.get("pxGlobals"),
                    result.get("main", {}).get("markersFound"),
                    result.get("pxScripts"),
                )
                return "perimeterx"
    except Exception as exc:
        logger.debug("PX detection failed: %s", exc)

    return None


def is_px_visible(page: Any) -> bool:
    """Quick check if PX challenge UI is currently visible on the page.

    This is a lighter check than detect_px(), suitable for polling loops.

    Args:
        page: Playwright Page object.

    Returns:
        True if PX challenge UI appears to be visible.
    """
    try:
        result = page.evaluate(
            """() => {
                // iframe modal (iFood variant)
                if (document.getElementById('px-captcha-modal')) return true;
                // direct px-captcha element (Walmart variant)
                const pxDiv = document.getElementById('px-captcha');
                if (pxDiv) return true;
                // shadow DOM px-captcha
                for (const el of document.querySelectorAll('*')) {
                    if (el.shadowRoot && el.shadowRoot.querySelector('#px-captcha')) return true;
                }
                // Check for PX script presence in page
                const scripts = document.querySelectorAll('script');
                for (const s of scripts) {
                    if (s.src && s.src.includes('px-cloud.net')) return true;
                }
                // Check body text for PX markers
                const body = (document.body ? document.body.innerText : '') || '';
                if (body.toLowerCase().includes('robot or human')) return true;
                if (body.toLowerCase().includes('activate and hold')) return true;
                const markers = """ + str(list(PX_TEXT_MARKERS)) + """;
                for (const m of markers) {
                    if (body.toLowerCase().includes(m)) return true;
                }
                return false;
            }"""
        )
        return bool(result)
    except Exception:
        return False


def is_px_block_page(page: Any) -> bool:
    """Check if the current page is a full PX block page (not a modal overlay).

    Args:
        page: Playwright Page object.

    Returns:
        True if the page itself is a PX challenge page (not the target content).
    """
    try:
        result = page.evaluate(
            """() => {
                const body = (document.body ? document.body.innerText : '') || '';
                const allMarkers = """ + str(list(PX_TEXT_MARKERS) + ["activate and hold", "robot or human"]) + """;
                const hasMarkers = allMarkers.some(
                    m => body.toLowerCase().includes(m)
                );
                const pxEl = document.querySelector(
                    '#px-captcha, #px-captcha-modal, .re-captcha'
                );
                return hasMarkers && (pxEl !== null || document.title.toLowerCase().includes('captcha'));
            }"""
        )
        return bool(result)
    except Exception:
        return False