#!/usr/bin/env python3
"""Fetch weight/body composition data from Health Planet API (TANITA).

OAuth 2.0 flow automated via Playwright for browser login.

Usage:
  python3 healthplanet-fetch.py              # Last 3 months of data
  python3 healthplanet-fetch.py --days 7     # Last 7 days
  python3 healthplanet-fetch.py --days 30    # Last 30 days
"""
import os
import sys
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

CLIENT_ID = os.environ.get("HP_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("HP_CLIENT_SECRET", "")
HP_USER = os.environ.get("HP_USER", "")
HP_PASSWORD = os.environ.get("HP_PASSWORD", "")
REDIRECT_URI = "https://www.healthplanet.jp/success.html"
TOKEN_CACHE = Path(__file__).parent / ".healthplanet_token.json"

TAG_NAMES = {
    "6021": "体重(kg)",
    "6022": "体脂肪率(%)",
}


def get_cached_token():
    """Return cached access_token if still valid."""
    if TOKEN_CACHE.exists():
        data = json.loads(TOKEN_CACHE.read_text())
        expires_at = data.get("expires_at", 0)
        if datetime.now().timestamp() < expires_at:
            return data["access_token"]
    return None


def save_token(token_data):
    """Cache token with expiry."""
    expires_in = token_data.get("expires_in", 2592000)  # default 30 days
    token_data["expires_at"] = datetime.now().timestamp() + expires_in
    TOKEN_CACHE.write_text(json.dumps(token_data))


def oauth_authorize():
    """Perform OAuth flow via Playwright to get authorization code."""
    from playwright.sync_api import sync_playwright

    auth_url = (
        f"https://www.healthplanet.jp/oauth/auth?"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        f"scope=innerscan&"
        f"response_type=code"
    )

    print("[hp] Starting OAuth authorization...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(auth_url, wait_until="networkidle")

        # Health Planet login page
        print(f"[hp] Login page: {page.url}")

        # Fill login form
        page.fill('input[name="loginId"]', HP_USER)
        page.fill('input[name="passwd"]', HP_PASSWORD)

        # Click login button (input type="image")
        page.click('input[type="image"]')
        page.wait_for_load_state("networkidle")
        print(f"[hp] After login: {page.url}")

        # Approve the OAuth scope — check for approval form
        approval_input = page.query_selector('input[name="approval"]')
        if approval_input:
            print("[hp] Approval page detected, granting access...")
            page.evaluate("""
                document.querySelector('input[name="approval"]').value = 'true';
            """)
            with page.expect_navigation(wait_until="networkidle"):
                page.evaluate("document.querySelector('form').submit();")
            print(f"[hp] After approval: {page.url}")

        # Extract authorization code
        code = None

        # Case 1: Code displayed in textarea on code display page
        textarea = page.query_selector("textarea")
        if textarea:
            code = (textarea.input_value() or "").strip()

        # Case 2: Code in URL query param (redirect case)
        if not code:
            parsed = urllib.parse.urlparse(page.url)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [None])[0]

        current_url = page.url
        browser.close()

    if not code:
        print(f"[hp] Failed to get auth code. Final URL: {current_url}")
        return None

    print(f"[hp] Got authorization code: {code[:20]}...")
    return code


def exchange_token(code):
    """Exchange authorization code for access token."""
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request("https://www.healthplanet.jp/oauth/token", data=data)
    resp = urllib.request.urlopen(req)
    token_data = json.loads(resp.read())

    if "access_token" in token_data:
        save_token(token_data)
        print(f"[hp] Token obtained, expires in {token_data.get('expires_in', '?')}s")
        return token_data["access_token"]
    else:
        print(f"[hp] Token error: {token_data}")
        return None


def get_access_token():
    """Get valid access token (cached or fresh)."""
    token = get_cached_token()
    if token:
        print("[hp] Using cached token")
        return token

    code = oauth_authorize()
    if not code:
        return None
    return exchange_token(code)


def fetch_innerscan(access_token, days=90):
    """Fetch body composition data from Health Planet API."""
    now = datetime.now()
    dt_from = (now - timedelta(days=days)).strftime("%Y%m%d%H%M%S")
    dt_to = now.strftime("%Y%m%d%H%M%S")

    params = urllib.parse.urlencode({
        "access_token": access_token,
        "date": "1",  # measurement date
        "from": dt_from,
        "to": dt_to,
        "tag": "6021,6022",  # weight, body fat %
    })

    url = f"https://www.healthplanet.jp/status/innerscan.json?{params}"
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def format_results(data):
    """Format innerscan data into readable output."""
    if not data or "data" not in data:
        print("[hp] No data returned")
        return

    info = {
        "sex": data.get("sex", ""),
        "height": data.get("height", ""),
        "birth_date": data.get("birth_date", ""),
    }
    print(f"[hp] Profile: sex={info['sex']}, height={info['height']}cm, birth={info['birth_date']}")

    # Group by date
    by_date = {}
    for d in data["data"]:
        date_str = d["date"]  # yyyyMMddHHmm
        day = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        time = f"{date_str[8:10]}:{date_str[10:12]}"
        tag = d["tag"]
        value = d["keydata"]

        key = f"{day} {time}"
        if key not in by_date:
            by_date[key] = {}
        by_date[key][tag] = float(value)

    # Print table
    print(f"\n{'日時':<20} {'体重(kg)':>10} {'体脂肪率(%)':>12}")
    print("-" * 44)
    for dt in sorted(by_date.keys()):
        vals = by_date[dt]
        weight = vals.get("6021", "")
        fat = vals.get("6022", "")
        w_str = f"{weight:.1f}" if weight else "-"
        f_str = f"{fat:.1f}" if fat else "-"
        print(f"{dt:<20} {w_str:>10} {f_str:>12}")

    # Latest values
    latest_key = sorted(by_date.keys())[-1] if by_date else None
    if latest_key:
        latest = by_date[latest_key]
        print(f"\n[hp] 最新: {latest_key}")
        if "6021" in latest:
            print(f"  体重: {latest['6021']:.1f} kg")
        if "6022" in latest:
            print(f"  体脂肪率: {latest['6022']:.1f} %")

    return by_date


def main():
    args = sys.argv[1:]
    days = 90

    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])

    token = get_access_token()
    if not token:
        print("[hp] Failed to get access token")
        sys.exit(1)

    print(f"[hp] Fetching innerscan data (last {days} days)...")
    data = fetch_innerscan(token, days)

    if data:
        results = format_results(data)
        # Save raw JSON
        out_path = "/tmp/healthplanet_data.json"
        Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"\n[hp] Raw data saved: {out_path}")


if __name__ == "__main__":
    main()
