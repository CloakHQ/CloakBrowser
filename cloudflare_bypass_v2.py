#!/usr/bin/env python3
"""
Advanced Cloudflare Bypass Tool - Version 2
Enhanced with additional techniques for harder challenges.

This version includes:
1. Multiple browser impersonation profiles
2. Advanced TLS fingerprint manipulation
3. Request timing and pattern randomization
4. Session persistence and cookie management
5. Proxy support (optional)
6. Custom challenge solving strategies
"""

import random
import time
import json
import hashlib
from typing import Optional, Dict, Any, List
from fake_useragent import UserAgent
from curl_cffi import requests as curl_requests
from curl_cffi.requests import BrowserType


class AdvancedCloudflareBypasser:
    """Advanced Cloudflare bypass with multiple strategies."""
    
    # Browser profiles with different TLS fingerprints
    BROWSER_PROFILES = [
        BrowserType.chrome120,
        BrowserType.chrome119,
        BrowserType.chrome116,
        BrowserType.chrome110,
        BrowserType.edge101,
        BrowserType.edge99,
        BrowserType.safari15_3,
        BrowserType.safari15_5,
    ]
    
    def __init__(self, verbose: bool = True, use_proxy: Optional[str] = None):
        self.verbose = verbose
        self.ua = UserAgent()
        self.cookies = {}
        self.use_proxy = use_proxy
        self.session_history = []
        
        # Cloudflare detection patterns
        self.cf_indicators = [
            'cf_chl_opt',
            'cf_ray',
            '__cf_chl_tk',
            'cf-spinner',
            'Checking your browser',
            'Just a moment...',
            'cf-challenge',
            'data-turbo="false"',
        ]
        
        # Success indicators
        self.success_indicators = [
            '<!doctype html>',
            '<html',
            '<head>',
            '<body>',
        ]
    
    def _log(self, message: str):
        """Log messages if verbose mode is enabled."""
        if self.verbose:
            timestamp = time.strftime('%H:%M:%S')
            print(f"[{timestamp}] {message}")
    
    def _human_delay(self) -> float:
        """Generate human-like delay with variation."""
        base_delay = random.gauss(0.5, 0.2)
        return max(0.1, min(2.0, base_delay))
    
    def _generate_headers(self, url: str, browser_type: BrowserType = None) -> Dict[str, str]:
        """Generate realistic headers based on browser type."""
        user_agent = self.ua.random
        
        from urllib.parse import urlparse
        parsed = urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"
        
        # Base headers
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,en-GB;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        
        # Add browser-specific headers
        if browser_type in [BrowserType.chrome120, BrowserType.chrome119, BrowserType.chrome116, BrowserType.chrome110]:
            headers.update({
                'Sec-Ch-Ua': '"Chromium";v="120", "Not(A:Brand";v="24"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
            })
        elif browser_type in [BrowserType.edge101, BrowserType.edge99]:
            headers.update({
                'Sec-Ch-Ua': '"Chromium";v="101", "Microsoft Edge";v="101"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
            })
        elif browser_type in [BrowserType.safari15_3, BrowserType.safari15_5]:
            headers.update({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us',
            })
        
        # Add referer sometimes (not always)
        if random.random() > 0.3:
            headers['Referer'] = referer
        
        return headers
    
    def _is_cloudflare_page(self, html: str) -> bool:
        """Detect Cloudflare challenge page."""
        if not html or len(html) < 100:
            return False
        
        html_lower = html.lower()
        
        # Check for CF indicators
        cf_count = sum(1 for indicator in self.cf_indicators if indicator.lower() in html_lower)
        
        # Check for very short pages (typical of CF challenges)
        if len(html) < 3000 and cf_count > 0:
            return True
        
        # Check for CF-specific patterns
        if 'cloudflare' in html_lower and ('challenge' in html_lower or 'protect' in html_lower):
            return True
        
        # Special check for "Just a moment" pages
        if 'just a moment' in html_lower and len(html) < 10000:
            return True
        
        return cf_count >= 2
    
    def _is_success_page(self, html: str) -> bool:
        """Check if response is a successful page load."""
        if not html or len(html) < 500:
            return False
        
        html_lower = html.lower()
        
        # Should have HTML structure
        has_html = any(indicator in html_lower for indicator in self.success_indicators)
        
        # Should NOT have CF challenge indicators
        has_cf = self._is_cloudflare_page(html)
        
        return has_html and not has_cf
    
    def bypass(self, url: str, max_retries: int = 5, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Attempt to bypass Cloudflare using multiple strategies.
        
        Args:
            url: Target URL
            max_retries: Maximum number of attempts
            timeout: Request timeout
            
        Returns:
            Response dictionary or None
        """
        self._log(f"Starting advanced bypass for: {url}")
        
        best_result = None
        failed_attempts = []
        
        for attempt in range(1, max_retries + 1):
            try:
                self._log(f"Attempt {attempt}/{max_retries}")
                
                # Select random browser profile for this attempt
                browser_profile = random.choice(self.BROWSER_PROFILES)
                self._log(f"Using browser profile: {browser_profile.name}")
                
                # Generate headers matching the browser
                headers = self._generate_headers(url, browser_profile)
                
                # Human-like delay before request
                delay = self._human_delay()
                if attempt > 1:
                    delay *= attempt  # Increase delay on retries
                time.sleep(delay)
                
                # Prepare proxy if configured
                proxies = None
                if self.use_proxy:
                    proxies = {'http': self.use_proxy, 'https': self.use_proxy}
                
                # Make request with browser impersonation
                response = curl_requests.get(
                    url,
                    headers=headers,
                    cookies=self.cookies if attempt == 1 else {},
                    timeout=timeout,
                    allow_redirects=True,
                    impersonate=browser_profile,
                    proxies=proxies,
                )
                
                # Update cookies
                if response.cookies:
                    self.cookies.update(response.cookies)
                
                # Analyze response
                if self._is_cloudflare_page(response.text):
                    self._log("Cloudflare challenge detected")
                    failed_attempts.append({
                        'attempt': attempt,
                        'browser': browser_profile.name,
                        'status': response.status_code,
                    })
                    
                    if attempt < max_retries:
                        # Exponential backoff with jitter
                        wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                        self._log(f"Backing off for {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        self._log("Max retries reached with Cloudflare blocks")
                        
                elif self._is_success_page(response.text):
                    self._log(f"SUCCESS! Status: {response.status_code}")
                    self.session_history.append({
                        'url': url,
                        'timestamp': time.time(),
                        'browser': browser_profile.name,
                        'attempts': attempt,
                    })
                    
                    return {
                        'success': True,
                        'status_code': response.status_code,
                        'content': response.text,
                        'headers': dict(response.headers),
                        'cookies': dict(response.cookies),
                        'url': response.url,
                        'browser_profile': browser_profile.name,
                        'attempts_needed': attempt,
                    }
                else:
                    self._log(f"Uncertain response (status: {response.status_code})")
                    best_result = {
                        'success': False,
                        'status_code': response.status_code,
                        'content': response.text[:500],
                        'reason': 'uncertain_response',
                    }
                    
            except Exception as e:
                self._log(f"Error on attempt {attempt}: {type(e).__name__}: {str(e)}")
                failed_attempts.append({
                    'attempt': attempt,
                    'error': str(e),
                })
                
                if attempt < max_retries:
                    time.sleep(random.uniform(1, 3))
                continue
        
        # All attempts failed
        if failed_attempts:
            self._log(f"All {len(failed_attempts)} attempts failed")
            return {
                'success': False,
                'reason': 'all_attempts_failed',
                'failed_attempts': failed_attempts,
                'best_result': best_result,
            }
        
        return None
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about current session."""
        return {
            'total_requests': len(self.session_history),
            'successful_bypasses': len([s for s in self.session_history if s]),
            'cookies_stored': len(self.cookies),
            'session_history': self.session_history[-5:],  # Last 5 requests
        }


def run_advanced_tests():
    """Run comprehensive test suite."""
    print("=" * 70)
    print("Advanced Cloudflare Bypass Tool - Test Suite v2")
    print("=" * 70)
    
    bypasser = AdvancedCloudflareBypasser(verbose=True)
    
    # Test cases with varying difficulty
    test_cases = [
        {
            'name': 'No CAPTCHA Page',
            'url': 'https://nopecha.com/',
            'difficulty': 'Easy',
            'description': 'Basic Cloudflare protection without CAPTCHA',
        },
        {
            'name': 'HTTPBin (Control)',
            'url': 'https://httpbin.org/html',
            'difficulty': 'None',
            'description': 'No protection - control test',
        },
        {
            'name': 'NowSecure Challenge',
            'url': 'https://nowsecure.nl',
            'difficulty': 'Hard',
            'description': 'Known difficult Cloudflare challenge',
        },
        {
            'name': 'Scraping Course',
            'url': 'https://scrapingcourse.com/',
            'difficulty': 'Medium',
            'description': 'E-commerce site with protection',
        },
    ]
    
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"Test {i}: {test['name']}")
        print(f"Difficulty: {test['difficulty']}")
        print(f"URL: {test['url']}")
        print(f"Description: {test['description']}")
        print('='*70)
        
        result = bypasser.bypass(test['url'], max_retries=5)
        
        if result:
            if result.get('success'):
                print(f"\n✓ SUCCESS!")
                print(f"  Status Code: {result['status_code']}")
                print(f"  Content Length: {len(result['content'])} chars")
                print(f"  Browser Profile: {result.get('browser_profile', 'N/A')}")
                print(f"  Attempts Needed: {result.get('attempts_needed', 1)}")
                print(f"  Cookies: {len(result.get('cookies', {}))}")
                results.append({
                    'test': test['name'],
                    'status': 'PASS',
                    'difficulty': test['difficulty'],
                })
            else:
                print(f"\n✗ FAILED")
                print(f"  Reason: {result.get('reason', 'Unknown')}")
                if 'failed_attempts' in result:
                    print(f"  Failed Attempts: {len(result['failed_attempts'])}")
                results.append({
                    'test': test['name'],
                    'status': 'FAIL',
                    'difficulty': test['difficulty'],
                    'reason': result.get('reason'),
                })
        else:
            print(f"\n✗ FAILED - No response")
            results.append({
                'test': test['name'],
                'status': 'FAIL',
                'difficulty': test['difficulty'],
                'reason': 'No response',
            })
        
        # Delay between tests
        if i < len(test_cases):
            print("\nWaiting before next test...")
            time.sleep(3)
    
    # Summary
    print(f"\n{'='*70}")
    print("TEST SUMMARY")
    print('='*70)
    
    passed = sum(1 for r in results if r['status'] == 'PASS')
    total = len(results)
    success_rate = (passed / total * 100) if total > 0 else 0
    
    print(f"Passed: {passed}/{total} ({success_rate:.1f}%)")
    print(f"\nSession Stats:")
    stats = bypasser.get_session_stats()
    print(f"  Total Requests: {stats['total_requests']}")
    print(f"  Successful Bypasses: {stats['successful_bypasses']}")
    print(f"  Cookies Stored: {stats['cookies_stored']}")
    
    print(f"\nDetailed Results:")
    for r in results:
        status_icon = "✓" if r['status'] == 'PASS' else "✗"
        print(f"  {status_icon} [{r['difficulty']}] {r['test']}: {r['status']}")
        if r['status'] == 'FAIL' and 'reason' in r:
            print(f"      Reason: {r['reason']}")
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
        bypasser = AdvancedCloudflareBypasser(verbose=True)
        result = bypasser.bypass(target_url, max_retries=5)
        
        if result and result.get('success'):
            print("\n" + "="*60)
            print("✓ Successfully bypassed Cloudflare!")
            print("="*60)
            print(f"Status: {result['status_code']}")
            print(f"Content Length: {len(result['content'])} chars")
            print(f"Browser Profile: {result.get('browser_profile', 'N/A')}")
            print(f"Attempts: {result.get('attempts_needed', 1)}")
            print(f"\nFirst 500 chars:")
            print(result['content'][:500])
        else:
            print("\n" + "="*60)
            print("✗ Failed to bypass Cloudflare")
            print("="*60)
            if result:
                print(f"Reason: {result.get('reason', 'Unknown')}")
                if 'failed_attempts' in result:
                    print(f"Failed attempts log:")
                    for fa in result['failed_attempts']:
                        print(f"  - {fa}")
    else:
        run_advanced_tests()
