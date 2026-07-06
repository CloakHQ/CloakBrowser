#!/usr/bin/env python3
"""
Cloudflare Bypass Tool - Open Source Alternative
Inspired by techniques used in browser automation tools.

This tool uses multiple techniques to bypass Cloudflare protection:
1. TLS fingerprint impersonation (using curl_cffi)
2. Realistic browser headers and user agents
3. Proper cookie handling and session management
4. Request timing simulation
5. JavaScript challenge solving (when possible)

Note: This tool is for educational purposes and legitimate testing only.
Always respect website terms of service and robots.txt files.
"""

import random
import time
import json
from typing import Optional, Dict, Any
from fake_useragent import UserAgent
from curl_cffi import requests as curl_requests
from curl_cffi.requests import BrowserType


class CloudflareBypasser:
    """Main class for bypassing Cloudflare protection."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.ua = UserAgent()
        self.session = None
        self.cookies = {}
        
        # Common Cloudflare challenge indicators
        self.cf_indicators = [
            'cf_chl_opt',
            'cf_ray',
            '__cf_chl_tk',
            'cf-spinner',
            'Checking your browser',
            'Just a moment...',
        ]
        
    def _log(self, message: str):
        """Log messages if verbose mode is enabled."""
        if self.verbose:
            print(f"[INFO] {message}")
    
    def _get_random_delay(self, min_ms: int = 100, max_ms: int = 500) -> float:
        """Generate random delay to simulate human behavior."""
        return random.uniform(min_ms / 1000, max_ms / 1000)
    
    def _generate_headers(self, url: str) -> Dict[str, str]:
        """Generate realistic browser headers."""
        user_agent = self.ua.random
        
        # Get base domain for referer
        from urllib.parse import urlparse
        parsed = urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"
        
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Referer': referer,
        }
        
        # Add Chrome-specific headers
        if 'Chrome' in user_agent:
            headers['Sec-Ch-Ua'] = '"Chromium";v="120", "Not(A:Brand";v="24"'
            headers['Sec-Ch-Ua-Mobile'] = '?0'
            headers['Sec-Ch-Ua-Platform'] = '"Windows"'
        
        return headers
    
    def _is_cloudflare_page(self, html: str) -> bool:
        """Check if the response contains Cloudflare challenge page."""
        html_lower = html.lower()
        return any(indicator.lower() in html_lower for indicator in self.cf_indicators)
    
    def bypass(self, url: str, max_retries: int = 3, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Attempt to bypass Cloudflare protection and fetch the page.
        
        Args:
            url: Target URL
            max_retries: Maximum number of retry attempts
            timeout: Request timeout in seconds
            
        Returns:
            Dictionary with status, content, cookies, etc. or None if failed
        """
        self._log(f"Starting Cloudflare bypass for: {url}")
        
        for attempt in range(1, max_retries + 1):
            try:
                self._log(f"Attempt {attempt}/{max_retries}")
                
                # Generate fresh headers for each attempt
                headers = self._generate_headers(url)
                
                # Small delay before request (simulate human behavior)
                time.sleep(self._get_random_delay(200, 800))
                
                # Use curl_cffi with browser impersonation
                # This is key to bypassing Cloudflare's TLS fingerprinting
                response = curl_requests.get(
                    url,
                    headers=headers,
                    cookies=self.cookies,
                    timeout=timeout,
                    allow_redirects=True,
                    impersonate=random.choice([
                        BrowserType.chrome120,
                        BrowserType.chrome119,
                        BrowserType.chrome116,
                        BrowserType.edge101,
                    ]),
                )
                
                # Update cookies from response
                self.cookies.update(response.cookies)
                
                # Check if we got Cloudflare challenge
                if self._is_cloudflare_page(response.text):
                    self._log("Cloudflare challenge detected")
                    
                    if attempt < max_retries:
                        # Wait longer and retry with different impersonation
                        wait_time = random.uniform(2, 5)
                        self._log(f"Waiting {wait_time:.1f}s before retry...")
                        time.sleep(wait_time)
                        continue
                    else:
                        self._log("Max retries reached, still blocked by Cloudflare")
                        return {
                            'success': False,
                            'status_code': response.status_code,
                            'content': response.text[:500],
                            'reason': 'cloudflare_challenge',
                            'cookies': dict(response.cookies),
                        }
                
                # Success!
                self._log(f"Successfully bypassed Cloudflare! Status: {response.status_code}")
                return {
                    'success': True,
                    'status_code': response.status_code,
                    'content': response.text,
                    'headers': dict(response.headers),
                    'cookies': dict(response.cookies),
                    'url': response.url,
                }
                
            except Exception as e:
                self._log(f"Error on attempt {attempt}: {str(e)}")
                if attempt < max_retries:
                    time.sleep(self._get_random_delay(1000, 2000))
                continue
        
        return None
    
    def post_bypass(self, url: str, data: Dict, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        POST request with Cloudflare bypass.
        
        Args:
            url: Target URL
            data: POST data
            max_retries: Maximum retry attempts
            
        Returns:
            Response dictionary or None
        """
        self._log(f"Starting POST request with Cloudflare bypass for: {url}")
        
        for attempt in range(1, max_retries + 1):
            try:
                self._log(f"POST attempt {attempt}/{max_retries}")
                
                headers = self._generate_headers(url)
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                
                time.sleep(self._get_random_delay(300, 700))
                
                response = curl_requests.post(
                    url,
                    headers=headers,
                    cookies=self.cookies,
                    data=data,
                    timeout=30,
                    allow_redirects=True,
                    impersonate=random.choice([
                        BrowserType.chrome120,
                        BrowserType.chrome119,
                    ]),
                )
                
                self.cookies.update(response.cookies)
                
                if self._is_cloudflare_page(response.text):
                    if attempt < max_retries:
                        time.sleep(random.uniform(3, 6))
                        continue
                    else:
                        return {
                            'success': False,
                            'status_code': response.status_code,
                            'content': response.text[:500],
                            'reason': 'cloudflare_challenge',
                        }
                
                return {
                    'success': True,
                    'status_code': response.status_code,
                    'content': response.text,
                    'headers': dict(response.headers),
                    'cookies': dict(response.cookies),
                }
                
            except Exception as e:
                self._log(f"POST error on attempt {attempt}: {str(e)}")
                if attempt < max_retries:
                    time.sleep(self._get_random_delay(1000, 2000))
                continue
        
        return None


def test_bypass():
    """Test the Cloudflare bypass functionality."""
    print("=" * 60)
    print("Cloudflare Bypass Tool - Test Suite")
    print("=" * 60)
    
    bypasser = CloudflareBypasser(verbose=True)
    
    # Test URLs (use sites you have permission to test)
    test_cases = [
        {
            'name': 'Cloudflare Protected Site (Example)',
            'url': 'https://nopecha.com/',
            'description': 'Site with Cloudflare protection',
        },
        {
            'name': 'Regular Site (Control)',
            'url': 'https://httpbin.org/html',
            'description': 'Simple test endpoint',
        },
    ]
    
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}: {test['name']}")
        print(f"URL: {test['url']}")
        print(f"Description: {test['description']}")
        print('='*60)
        
        result = bypasser.bypass(test['url'])
        
        if result:
            if result['success']:
                print(f"\n✓ SUCCESS!")
                print(f"  Status Code: {result['status_code']}")
                print(f"  Content Length: {len(result['content'])} chars")
                print(f"  Cookies Received: {len(result['cookies'])}")
                results.append({'test': test['name'], 'status': 'PASS'})
            else:
                print(f"\n✗ FAILED")
                print(f"  Reason: {result.get('reason', 'Unknown')}")
                print(f"  Status Code: {result.get('status_code', 'N/A')}")
                results.append({'test': test['name'], 'status': 'FAIL', 'reason': result.get('reason')})
        else:
            print(f"\n✗ FAILED - No response")
            results.append({'test': test['name'], 'status': 'FAIL', 'reason': 'No response'})
        
        # Delay between tests
        if i < len(test_cases):
            time.sleep(2)
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print('='*60)
    passed = sum(1 for r in results if r['status'] == 'PASS')
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    for r in results:
        status_icon = "✓" if r['status'] == 'PASS' else "✗"
        print(f"  {status_icon} {r['test']}: {r['status']}")
        if r['status'] == 'FAIL' and 'reason' in r:
            print(f"      Reason: {r['reason']}")
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Custom URL from command line
        target_url = sys.argv[1]
        bypasser = CloudflareBypasser(verbose=True)
        result = bypasser.bypass(target_url)
        
        if result and result['success']:
            print("\n✓ Successfully bypassed Cloudflare!")
            print(f"Status: {result['status_code']}")
            print(f"Content preview: {result['content'][:300]}...")
        else:
            print("\n✗ Failed to bypass Cloudflare")
            if result:
                print(f"Reason: {result.get('reason', 'Unknown')}")
    else:
        # Run test suite
        test_bypass()
