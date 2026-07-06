#!/usr/bin/env python3
"""
Cloudflare Bypass Tool v3 — Hybrid approach
Combines: SeleniumBase UC Mode (real Chrome) + JS fetch() for per-route bypass

Strategy:
1. Use REAL Chrome (not patched CloakBrowser) via SeleniumBase UC Mode
2. uc_open_with_reconnect with LONG reconnect_time (disconnects chromedriver → CF sees normal browser)
3. uc_gui_click_captcha() to solve Turnstile checkbox
4. Once cf_clearance obtained, use JS fetch() INSIDE the browser to access other routes
   (JS fetch uses browser's TLS stack + cookies → CF doesn't challenge again)

This bypasses the "per-route challenge" problem where cf_clearance from route A
doesn't work for route B when using curl, but DOES work when using JS fetch()
inside the same browser context.
"""
import time
import json
import sys
import os

# Ensure DISPLAY is set for Xvfb
os.environ.setdefault("DISPLAY", ":99")

from seleniumbase import SB


def bypass_cloudflare(target_url, chrome_binary=None, extra_routes=None):
    """
    Bypass Cloudflare managed challenge and access target URL.
    
    Args:
        target_url: Main URL to bypass CF on
        chrome_binary: Path to Chrome binary (optional)
        extra_routes: List of additional paths to fetch via JS after bypass
    
    Returns:
        dict with results for each route
    """
    sb_kwargs = {
        "headless": False,
        "uc": True,
        "xvfb": False,
    }
    if chrome_binary:
        sb_kwargs["binary_location"] = chrome_binary
    
    results = {}
    
    with SB(**sb_kwargs) as sb:
        print(f"[INIT] SeleniumBase UC Mode launched", flush=True)
        
        # Step 1: Visit target URL with long reconnect time
        # reconnect_time=15 means: disconnect chromedriver for 15s, let CF see a "normal" browser
        print(f"[STEP 1] Visiting {target_url} (reconnect_time=15)...", flush=True)
        sb.uc_open_with_reconnect(target_url, reconnect_time=15)
        
        title = sb.get_title()
        print(f"[STEP 1] Title: {title}", flush=True)
        
        # Step 2: If CF challenge detected, click the Turnstile checkbox
        if "Just a moment" in title or "Performing security" in sb.get_text("body"):
            print(f"[STEP 2] CF challenge detected — clicking captcha...", flush=True)
            try:
                sb.uc_gui_click_captcha()
                print(f"[STEP 2] Captcha clicked!", flush=True)
            except Exception as e:
                print(f"[STEP 2] Captcha click error: {e}", flush=True)
            
            # Wait for CF to process the challenge
            print(f"[STEP 2] Waiting 15s for CF to process...", flush=True)
            time.sleep(15)
            
            title = sb.get_title()
            body = sb.get_text("body")
            print(f"[STEP 2] Title after wait: {title}", flush=True)
            print(f"[STEP 2] Body (first 300): {body[:300]}", flush=True)
        
        # Step 3: Check if CF bypassed
        cookies = sb.get_cookies()
        cookie_names = [c.get("name") for c in cookies]
        has_clearance = "cf_clearance" in cookie_names
        print(f"[STEP 3] Cookies: {cookie_names}", flush=True)
        print(f"[STEP 3] cf_clearance: {has_clearance}", flush=True)
        
        # Record main page result
        results["main"] = {
            "url": target_url,
            "status": "bypassed" if "Just a moment" not in title else "blocked",
            "title": title,
            "body": sb.get_text("body")[:5000],
            "cookies": {c.get("name"): c.get("value") for c in cookies},
        }
        
        # Step 4: If bypassed, use JS fetch() to access extra routes
        # This is the KEY technique: JS fetch() runs inside the browser,
        # using the browser's own TLS stack + cookies → CF doesn't challenge again
        if has_clearance or "Just a moment" not in title:
            if extra_routes:
                for route in extra_routes:
                    print(f"\n[STEP 4] JS fetch() to {route}...", flush=True)
                    
                    # Build the full URL
                    from urllib.parse import urlparse
                    parsed = urlparse(target_url)
                    full_url = f"{parsed.scheme}://{parsed.netloc}{route}"
                    
                    # Use JS fetch() — stays within browser TLS + cookie context
                    js_code = f"""
                        return new Promise((resolve) => {{
                            fetch('{full_url}', {{
                                method: 'GET',
                                credentials: 'include',
                                headers: {{
                                    'Accept': 'text/html,application/json,*/*'
                                }}
                            }}).then(r => {{
                                r.text().then(text => {{
                                    resolve({{
                                        status: r.status,
                                        body: text.substring(0, 10000),
                                        url: r.url,
                                        redirected: r.redirected
                                    }});
                                }});
                            }}).catch(e => {{
                                resolve({{error: e.toString()}});
                            }});
                        }});
                    """
                    
                    try:
                        result = sb.execute_script(js_code)
                        print(f"  Status: {result.get('status')}", flush=True)
                        body_preview = result.get("body", "")[:500]
                        print(f"  Body (first 500): {body_preview}", flush=True)
                        results[route] = result
                    except Exception as e:
                        print(f"  Error: {e}", flush=True)
                        results[route] = {"error": str(e)}
                    
                    time.sleep(2)
            
            # Also try POST requests
            if extra_routes:
                for route in extra_routes:
                    print(f"\n[STEP 5] JS POST to {route}...", flush=True)
                    from urllib.parse import urlparse
                    parsed = urlparse(target_url)
                    full_url = f"{parsed.scheme}://{parsed.netloc}{route}"
                    
                    js_code = f"""
                        return new Promise((resolve) => {{
                            fetch('{full_url}', {{
                                method: 'POST',
                                credentials: 'include',
                                headers: {{
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json'
                                }},
                                body: JSON.stringify({{}})
                            }}).then(r => {{
                                r.text().then(text => {{
                                    resolve({{
                                        status: r.status,
                                        body: text.substring(0, 10000)
                                    }});
                                }});
                            }}).catch(e => {{
                                resolve({{error: e.toString()}});
                            }});
                        }});
                    """
                    
                    try:
                        result = sb.execute_script(js_code)
                        print(f"  Status: {result.get('status')}", flush=True)
                        body_preview = result.get("body", "")[:500]
                        print(f"  Body (first 500): {body_preview}", flush=True)
                        results[f"POST:{route}"] = result
                    except Exception as e:
                        print(f"  Error: {e}", flush=True)
                        results[f"POST:{route}"] = {"error": str(e)}
                    
                    time.sleep(2)
        else:
            print(f"\n[FAIL] CF still blocking — cannot access extra routes", flush=True)
            sb.save_screenshot("/tmp/cf-blocked.png")
    
    return results


if __name__ == "__main__":
    # Default: test against sdk-h1.unico.io
    target = sys.argv[1] if len(sys.argv) > 1 else "https://sdk-h1.unico.io/"
    
    # Extra routes to fetch after CF bypass
    routes = ["/createprocess", "/docs", "/mobile-sdks"]
    
    # Try to find Chrome binary
    chrome_paths = [
        "/tmp/chrome-extracted/opt/google/chrome/chrome",  # Extracted real Chrome
        "/home/z/.cloakbrowser/chromium-146.0.7680.177.5/chrome",  # CloakBrowser
        None,  # Let SeleniumBase find it
    ]
    
    chrome_binary = None
    for p in chrome_paths:
        if p and os.path.exists(p):
            chrome_binary = p
            print(f"Using Chrome binary: {p}", flush=True)
            break
    
    print(f"\n{'='*60}")
    print(f"  Cloudflare Bypass v3 — Hybrid Approach")
    print(f"  Target: {target}")
    print(f"  Routes: {routes}")
    print(f"{'='*60}\n")
    
    results = bypass_cloudflare(target, chrome_binary=chrome_binary, extra_routes=routes)
    
    # Save results
    with open("/tmp/cf_bypass_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*60}")
    for key, val in results.items():
        status = val.get("status", "unknown") if isinstance(val, dict) else "unknown"
        body_len = len(val.get("body", "")) if isinstance(val, dict) else 0
        print(f"  {key:30s} | status={status} | body={body_len}B")
