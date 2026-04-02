#!/usr/bin/env python3
"""Fetch nutrition/weight data from asken.jp via browser automation.

Usage:
  python3 asken-fetch.py                    # Today's nutrition summary
  python3 asken-fetch.py --date 2026-04-01  # Specific date
  python3 asken-fetch.py --week             # Past 7 days
  python3 asken-fetch.py --graph            # Weight/health graph screenshot
"""
import os
import sys
import json
import re
from datetime import date, timedelta
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

EMAIL = os.environ.get("ASKEN_EMAIL", "")
PASSWORD = os.environ.get("ASKEN_PASSWORD", "")

if not EMAIL or not PASSWORD:
    print("Error: ASKEN_EMAIL and ASKEN_PASSWORD must be set in .env")
    sys.exit(1)

OUTPUT_DIR = "/tmp"


def login(page):
    """Login to asken.jp, returns True on success."""
    page.goto("https://www.asken.jp/login", wait_until="networkidle")
    page.fill("#CustomerMemberEmail", EMAIL)
    page.fill("#CustomerMemberPasswdPlain", PASSWORD)
    page.click("#SubmitSubmit")
    page.wait_for_load_state("networkidle")
    if "login" in page.url.lower() and "logout" not in page.url.lower():
        print("[asken] Login failed")
        return False
    print(f"[asken] Login OK")
    return True


def fetch_day(page, target_date):
    """Fetch nutrition data for a single day."""
    url = f"https://www.asken.jp/wsp/comment?date={target_date}"
    page.goto(url, wait_until="networkidle")

    text = page.inner_text("body")
    screenshot_path = f"{OUTPUT_DIR}/asken_{target_date}.png"
    page.screenshot(path=screenshot_path, full_page=True)

    # Parse calories
    result = {
        "date": target_date,
        "recorded": "まだ記録されていません" not in text[:500],
        "screenshot": screenshot_path,
    }

    # Extract calorie data: pattern "NNNNkcal"
    kcals = re.findall(r"(\d[\d,]+)\s*kcal", text)
    if kcals:
        result["target_kcal"] = int(kcals[0].replace(",", ""))
        if len(kcals) >= 2:
            result["intake_kcal"] = int(kcals[1].replace(",", ""))

    # Extract nutrient bars/values
    # Look for common nutrient names in Japanese
    nutrients = {}
    for nutrient in ["たんぱく質", "脂質", "炭水化物", "食物繊維", "カルシウム",
                     "鉄", "ビタミンA", "ビタミンB1", "ビタミンB2", "ビタミンC",
                     "ビタミンD", "ビタミンE", "塩分", "糖質", "飽和脂肪酸"]:
        pattern = rf"{nutrient}\s*[：:]?\s*([\d.]+)\s*(g|mg|μg|%)"
        m = re.search(pattern, text)
        if m:
            nutrients[nutrient] = {"value": float(m.group(1)), "unit": m.group(2)}
    result["nutrients"] = nutrients

    # Extract meal details
    meals = {}
    for meal_name in ["朝食", "昼食", "夕食", "間食"]:
        idx = text.find(meal_name)
        if idx >= 0:
            section = text[idx:idx + 500]
            if "まだ記録されていません" in section:
                meals[meal_name] = {"recorded": False}
            else:
                meals[meal_name] = {"recorded": True, "text": section[:300]}
    result["meals"] = meals

    return result


def fetch_graph(page):
    """Fetch weight/health graph and meal graph screenshots."""
    paths = {}

    for name, url in [
        ("weight", "https://www.asken.jp/my_graph/weightfat"),
        ("health", "https://www.asken.jp/my_graph/point"),
        ("meal", "https://www.asken.jp/my_graph/meal"),
    ]:
        page.goto(url, wait_until="networkidle")
        path = f"{OUTPUT_DIR}/asken_graph_{name}.png"
        page.screenshot(path=path, full_page=True)
        paths[name] = path
        print(f"[asken] Graph {name}: {path}")

    return paths


def main():
    args = sys.argv[1:]
    week_mode = "--week" in args
    graph_mode = "--graph" in args
    target_date = None

    for i, a in enumerate(args):
        if a == "--date" and i + 1 < len(args):
            target_date = args[i + 1]

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        if not login(page):
            browser.close()
            sys.exit(1)

        if graph_mode:
            paths = fetch_graph(page)
            print(json.dumps(paths, ensure_ascii=False, indent=2))
        elif week_mode:
            today = date.today()
            results = []
            for d in range(7):
                dt = (today - timedelta(days=6 - d)).isoformat()
                result = fetch_day(page, dt)
                results.append(result)
                status = "✓" if result["recorded"] else "–"
                kcal = result.get("intake_kcal", "-")
                print(f"  {status} {dt}: {kcal} kcal")
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            if target_date is None:
                target_date = date.today().isoformat()
            result = fetch_day(page, target_date)
            print(json.dumps(result, ensure_ascii=False, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
