# Human Behavior Simulation

By passing `humanize=True` to the launcher, CloakBrowser intercepts and replaces standard automation commands (`page.click()`, `page.fill()`, `page.type()`, `page.hover()`, `page.mouse.*`, `page.keyboard.*`) with human-mimicking movements. 

This behavioral masking prevents advanced server-side scorekeepers (like reCAPTCHA v3, Turnstile, and DataDome) from flagging your automation sequence as bot traffic.

## Quick Start

```python
from cloakbrowser import launch

browser = launch(
    humanize=True,
    human_preset="default",  # "default" or "careful"
)
page = browser.new_page()
page.goto("https://protected-site.com")

# The locator API automatically applies Bézier curve aiming and typo simulation!
page.locator("#username").fill("user@example.com")
page.locator("button[type=submit]").click()
```

---

## Humanization Evasion Details

| Action | Standard Playwright | With `humanize=True` |
|---|---|---|
| **Mouse Movements** | Instant teleportation (0ms) to target coordinates. | Custom Bézier curve movements with natural easing and overshoot. |
| **Clicks** | Clicks exact center of element instantly. | Realistic aim point (offset from exact center) + natural press-and-hold duration (50-150ms). |
| **Keyboard Inputs** | Instantly dumps the entire text string. | Clear field, character-by-character typing with natural delays, thinking pauses, and random typos with self-correction. |
| **Scrolling** | Jumps instantly to coordinates. | Smooth scroll curve (Accelerate → Cruise → Decelerate) in micro-steps. |
| **Thinking Pauses** | Actions occur back-to-back at lightspeed. | Injects micro-movements and idle pauses between distinct actions to emulate human reading. |

---

## Configuration Presets & Custom Fine-Tuning

### Presets
- `"default"`: Fast but highly natural. Good for general anti-bot challenges and normal scrapers.
- `"careful"`: Slower, adds more deliberate movements, idle micro-movements between operations. Essential for Akamai and Kasada.

### Custom Tuning via `human_config`
You can fine-tune human behaviors down to individual parameters:

```python
browser = launch(
    humanize=True,
    human_config={
        "mistype_chance": 0.05,              # 5% chance of making a typo per character
        "typing_delay": 120,                 # Base delay between keystrokes (ms)
        "idle_between_actions": True,        # Perform idle mouse drifts between actions
        "idle_between_duration": [0.4, 0.9], # Duration bounds for idle drifts (seconds)
    }
)
```

---

## Evasion Strategies for reCAPTCHA v3 & Enterprise

reCAPTCHA v3 calculates scores between `0.1` (bot) and `0.9` (human) based on historical page interaction. To guarantee a `0.9` score, enforce the following guidelines in your scripts:

### 1. Let the Page Breathe
Do not immediately navigate, type, and submit. Real humans take time to read.
```python
import time

page.goto("https://recaptcha-demo.com")
time.sleep(3)  # Emulate user reading above the fold
```

### 2. Mimic Content Reading (Scroll First)
Before filling forms, scroll down and back up:
```python
# Scroll down slightly to make reading behavior look genuine
page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
time.sleep(2)
page.evaluate("window.scrollTo(0, 0)")
time.sleep(1)
```

### 3. Use Locator API over ElementHandles
Avoid using `page.query_selector()` (ElementHandles) to click elements, as they bypass the humanize wrappers. **Always use Locator API** or selector-based methods:
```python
# GOOD (Humanized)
page.locator("#submit").click()
page.click("#submit")

# AVOID (CDP direct bypass - teleports mouse)
el = page.query_selector("#submit")
el.click()
```

### 4. Direct Bypass for Speed
If you need high-speed execution for safe sites or during testing, you can bypass the humanizer for a specific page call by accessing the original page object:
```python
# Bypasses humanizer curves, teleports instantly
page._original.click("#safe-element")
```
