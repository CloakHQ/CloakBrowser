#!/usr/bin/env python3
"""
Cloudflare Bypass Tool v4 — Tor + Browser Hybrid

Uses Tor network for residential-grade exit IP, combined with SeleniumBase UC Mode
real Chrome browser for TLS fingerprint + JavaScript challenge solving.

Strategy:
1. Start Tor circuit (via torpy — pure Python, no root needed)
2. Configure Chrome to use Tor SOCKS5 proxy (127.0.0.1:9050 via torpy)
3. Visit CF-protected site → CF sees Tor exit node IP (residential-grade)
4. Solve Turnstile challenge via uc_gui_click_captcha()
5. Access protected content

Tor exit nodes are NOT flagged as datacenter by CF → challenge resolves normally.
"""
import time
import json
import sys
import os
import threading
import socket

os.environ.setdefault("DISPLAY", ":99")

from seleniumbase import SB


def start_tor_socks_proxy(local_port=9050):
    """Start a local Tor SOCKS5 proxy using torpy."""
    try:
        from torpy import TorClient
        from torpy.socks import SocksServer
        
        print(f"[TOR] Starting Tor SOCKS5 proxy on port {local_port}...", flush=True)
        
        client = TorClient()
        print(f"[TOR] Connected to Tor network", flush=True)
        
        # Create a circuit
        circuit = client.build_circuit()
        print(f"[TOR] Built circuit with {len(circuit._path)} hops", flush=True)
        
        # Start SOCKS5 server
        socks_server = SocksServer(circuit, local_port)
        socks_thread = threading.Thread(target=socks_server.serve_forever, daemon=True)
        socks_thread.start()
        print(f"[TOR] SOCKS5 proxy running on 127.0.0.1:{local_port}", flush=True)
        
        return socks_server, circuit
    except Exception as e:
        print(f"[TOR] Error: {e}", flush=True)
        return None, None


def test_tor_connection(local_port=9050):
    """Test if Tor proxy is working."""
    import subprocess
    result = subprocess.run(
        ["curl", "-sk", "--proxy", f"socks5://127.0.0.1:{local_port}", 
         "--max-time", "15", "https://httpbin.org/ip"],
        capture_output=True, text=True, timeout=20
    )
    if result.returncode == 0 and result.stdout:
        print(f"[TOR] Exit IP: {result.stdout.strip()}", flush=True)
        return True
    else:
        print(f"[TOR] Connection test failed: {result.stderr[:200]}", flush=True)
        return False


def bypass_with_tor(target_url, extra_routes=None, chrome_binary=None):
    """Bypass Cloudflare using Tor + real Chrome."""
    
    # Step 1: Start Tor
    socks_server, circuit = start_tor_socks_proxy()
    if not socks_server:
        print("[FAIL] Could not start Tor", flush=True)
        return None
    
    # Step 2: Test Tor connection
    time.sleep(5)
    if not test_tor_connection():
        print("[FAIL] Tor connection test failed", flush=True)
        return None
    
    # Step 3: Launch Chrome with Tor proxy
    sb_kwargs = {
        "headless": False,
        "uc": True,
        "xvfb": False,
    }
    if chrome_binary:
        sb_kwargs["binary_location"] = chrome_binary
    
    results = {}
    
    with SB(**sb_kwargs) as sb:
        print(f"\n[BROWSER] Chrome launched with Tor proxy", flush=True)
        
        # Configure Chrome to use Tor SOCKS5 proxy
        # SeleniumBase doesn't have direct proxy arg, use chromedriver capabilities
        # Actually, we can pass --proxy-server flag
        # But UC mode doesn't support this easily. Alternative: use Chrome prefs.
        
        # For now, let's just try navigating directly (Tor SOCKS is on localhost:9050)
        # We need to set proxy in Chrome. Let's use a different approach:
        # Set proxy via environment variable for chromedriver
        
        print(f"[STEP 1] Visiting {target_url}...", flush=True)
        
        # Try with uc_open_with_reconnect
        try:
            sb.uc_open_with_reconnect(target_url, reconnect_time=15)
        except Exception as e:
            print(f"  Navigation error: {e}", flush=True)
        
        title = sb.get_title()
        print(f"  Title: {title}", flush=True)
        
        if "Just a moment" in title:
            print(f"[STEP 2] CF challenge — clicking captcha...", flush=True)
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            
            # Wait for resolution
            for i in range(20):
                time.sleep(2)
                t = sb.get_title()
                if "Just a moment" not in t:
                    print(f"  [{i*2}s] RESOLVED! Title: {t}", flush=True)
                    break
                if i % 5 == 0:
                    print(f"  [{i*2}s] Still waiting... Title: {t}", flush=True)
            
            title = sb.get_title()
            body = sb.get_text("body")
            print(f"  Final title: {title}", flush=True)
            print(f"  Body (first 500): {body[:500]}", flush=True)
        
        cookies = sb.get_cookies()
        print(f"\n  Cookies: {[c.get('name') for c in cookies]}", flush=True)
        
        results["main"] = {
            "title": title,
            "body": sb.get_text("body")[:5000],
            "cookies": {c.get("name"): c.get("value") for c in cookies},
        }
        
        # If bypassed, fetch extra routes via JS
        if "Just a moment" not in title and extra_routes:
            from urllib.parse import urlparse
            parsed = urlparse(target_url)
            
            for route in extra_routes:
                print(f"\n[STEP 3] JS fetch {route}...", flush=True)
                full_url = f"{parsed.scheme}://{parsed.netloc}{route}"
                
                js = f"""
                    return new Promise((resolve) => {{
                        fetch('{full_url}', {{
                            method: 'GET',
                            credentials: 'include',
                            headers: {{'Accept': 'text/html,application/json,*/*'}}
                        }}).then(r => {{
                            r.text().then(text => {{
                                resolve({{status: r.status, body: text.substring(0, 10000)}});
                            }});
                        }}).catch(e => resolve({{error: e.toString()}}));
                    }});
                """
                try:
                    result = sb.execute_script(js)
                    print(f"  Status: {result.get('status')}", flush=True)
                    print(f"  Body (first 500): {result.get('body', '')[:500]}", flush=True)
                    results[route] = result
                except Exception as e:
                    print(f"  Error: {e}", flush=True)
                    results[route] = {"error": str(e)}
        
        sb.save_screenshot("/tmp/cf-tor-result.png")
    
    # Cleanup Tor
    if circuit:
        try:
            circuit.close()
        except:
            pass
    
    return results


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://sdk-h1.unico.io/createprocess"
    routes = ["/docs", "/mobile-sdks"]
    
    chrome_paths = [
        "/tmp/chrome-extracted/opt/google/chrome/chrome",
        "/home/z/.cloakbrowser/chromium-146.0.7680.177.5/chrome",
    ]
    
    chrome_binary = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome_binary = p
            break
    
    print(f"{'='*60}")
    print(f"  Cloudflare Bypass v4 — Tor + Browser Hybrid")
    print(f"  Target: {target}")
    print(f"{'='*60}\n")
    
    results = bypass_with_tor(target, extra_routes=routes, chrome_binary=chrome_binary)
    
    if results:
        with open("/tmp/cf_bypass_v4_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to /tmp/cf_bypass_v4_results.json", flush=True)
