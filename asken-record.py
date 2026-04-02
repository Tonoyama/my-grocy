#!/usr/bin/env python3
"""Record meals to asken.jp via browser automation.

Usage:
  python3 asken-record.py --date 2026-04-02 --meal lunch --items '豚汁:1,そうめん・ひやむぎ(麺のみ・ゆで)(乾麺100g分):0.5'
  python3 asken-record.py --date 2026-04-02 --meal dinner --items '鮭の味噌焼き:1,ほうれん草のおひたし:1'

Arguments:
  --date    YYYY-MM-DD format
  --meal    breakfast/lunch/dinner/sweets
  --items   Comma-separated 'search_term:quantity' pairs (quantity in servings)
"""
import os
import sys
import json
import re
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

MEAL_TYPES = {
    "breakfast": "breakfast", "朝食": "breakfast",
    "lunch": "lunch", "昼食": "lunch",
    "dinner": "dinner", "夕食": "dinner",
    "sweets": "sweets", "間食": "sweets",
}


def record_meals(target_date, meal_type, items):
    """Record meals to asken.

    items: list of (search_term, quantity) tuples
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.set_default_timeout(30000)
        page = ctx.new_page()

        # Login
        page.goto("https://www.asken.jp/login", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.fill("#CustomerMemberEmail", EMAIL)
        page.fill("#CustomerMemberPasswdPlain", PASSWORD)
        page.click("#SubmitSubmit")
        page.wait_for_timeout(5000)
        print(f"[asken] Login OK")

        results = []
        for search_term, quantity in items:
            # Navigate to meal page fresh for each item
            page.goto(
                f"https://www.asken.jp/wsp/meal/{meal_type}/{target_date}",
                wait_until="domcontentloaded"
            )
            page.wait_for_timeout(5000)

            # Search
            page.fill("#search_input", search_term)
            page.press("#search_input", "Enter")
            page.wait_for_timeout(4000)

            # Click first matching result
            search_results = page.locator(f'a[onclick*="choseMenuBySearch"]').all()
            clicked = False
            for sr in search_results:
                text = (sr.inner_text() or "").strip()
                onclick = sr.get_attribute("onclick") or ""
                if search_term.lower() in text.lower():
                    sr.click(force=True)
                    clicked = True
                    print(f"  Selected: {text}")
                    break

            if not clicked and search_results:
                search_results[0].click(force=True)
                print(f"  Selected first result")

            page.wait_for_timeout(3000)

            # Set quantity and submit via API
            page.evaluate(f'V2WspMeal.step3.choseQuantity("{quantity}")')
            page.wait_for_timeout(1000)

            r = page.evaluate(f"""
                (async () => {{
                    var form = document.getElementById('step3_form');
                    if (!form) return {{status: 0, body: 'No form found'}};
                    var formData = new URLSearchParams(new FormData(form));
                    var resp = await fetch('/meal/add_menu?meal_type={meal_type}&record_date={target_date}', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest'}},
                        body: formData.toString()
                    }});
                    var text = await resp.text();
                    return {{status: resp.status, body: text.substring(0, 300)}};
                }})()
            """)

            status = r.get("status", 0)
            body = r.get("body", "")
            ok = status == 200 and '"OK"' in body

            # Extract energy
            energy = ""
            m = re.search(r'"add_energy":(\d+)', body)
            if m:
                energy = f"{m.group(1)}kcal"

            results.append({
                "item": search_term,
                "quantity": quantity,
                "ok": ok,
                "energy": energy,
            })
            mark = "✓" if ok else "✗"
            print(f"  {mark} {search_term} x{quantity} {energy}")

        browser.close()
        return results


def main():
    args = sys.argv[1:]
    target_date = None
    meal_type = "lunch"
    items_str = ""

    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            target_date = args[i + 1]
            i += 2
        elif args[i] == "--meal" and i + 1 < len(args):
            meal_type = MEAL_TYPES.get(args[i + 1], args[i + 1])
            i += 2
        elif args[i] == "--items" and i + 1 < len(args):
            items_str = args[i + 1]
            i += 2
        else:
            i += 1

    if not target_date or not items_str:
        print("Usage: python3 asken-record.py --date YYYY-MM-DD --meal lunch --items 'name:qty,name:qty'")
        sys.exit(1)

    # Parse items
    items = []
    for part in items_str.split(","):
        part = part.strip()
        if ":" in part:
            name, qty = part.rsplit(":", 1)
            items.append((name.strip(), qty.strip()))

    print(f"[asken] Recording {meal_type} for {target_date}: {len(items)} items")
    results = record_meals(target_date, meal_type, items)

    total_ok = sum(1 for r in results if r["ok"])
    print(f"\n[asken] Done: {total_ok}/{len(results)} items recorded")


if __name__ == "__main__":
    main()
PYEOF