#!/usr/bin/env python3
"""Kitchen App server.
Serves the unified SPA, provides API endpoints for stock/mealplan/deals,
and bridges voice commands to Claude Code CLI.
"""
import subprocess
import json
import os
import re
import sqlite3
import mimetypes
from datetime import date, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(WORK_DIR, "static")
GROCY_DB = os.path.join(WORK_DIR, "grocy-config", "data", "grocy.db")
HACHI_DB = "/Users/ytonoyam/Dev/hachimenroppi/data/hachimenroppi.db"


def query_db(db_path, sql, params=()):
    """Query SQLite database in read-only mode."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def parse_recipe_description(desc):
    """Parse recipe description into structured data."""
    if not desc:
        return {"title": "", "ingredients": [], "methods": [], "storage": ""}

    ingredients = []
    methods = []  # list of {name, steps}
    storage = ""
    title = ""

    # Extract title line (【...】)
    m = re.match(r"【(.+?)】", desc)
    if m:
        title = m.group(1)

    parts = desc.split("■")
    for part in parts:
        part = part.strip()
        if part.startswith("材料"):
            for line in part.split("\n")[1:]:
                line = line.strip().lstrip("・")
                if line and not line.startswith("※"):
                    ingredients.append(line)
        elif part.startswith("作り方"):
            method_name = ""
            steps = []
            first_line = part.split("\n")[0]
            # Check for method variant like 作り方【オーブントースター】
            vm = re.search(r"【(.+?)】", first_line)
            if vm:
                method_name = vm.group(1)
            for line in part.split("\n")[1:]:
                line = line.strip()
                if line and line[0].isdigit():
                    step_text = re.sub(r"^\d+[\.\)、]\s*", "", line)
                    steps.append(step_text)
            methods.append({"name": method_name, "steps": steps})
        elif part.startswith("保存"):
            storage_lines = []
            for line in part.split("\n")[1:]:
                line = line.strip().lstrip("・")
                if line:
                    storage_lines.append(line)
            storage = " ".join(storage_lines)

    return {"title": title, "ingredients": ingredients, "methods": methods, "storage": storage}


class Handler(BaseHTTPRequestHandler):

    # ── GET ──────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path.startswith("/api/"):
            self._route_api(path, qs)
        else:
            self._serve_static(path)

    def _route_api(self, path, qs):
        try:
            if path == "/api/stock":
                self._api_stock()
            elif path == "/api/mealplan":
                self._api_mealplan(qs)
            elif path == "/api/mealplan/cooking-guide":
                self._api_cooking_guide(qs)
            elif path == "/api/deals":
                self._api_deals(qs)
            elif path == "/api/deals/categories":
                self._api_deals_categories()
            else:
                self._json(404, {"error": "not found"})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _api_stock(self):
        rows = query_db(GROCY_DB, """
            SELECT p.id, p.name, sc.amount, sc.best_before_date, l.name as location, s.price,
                   qu.name as unit
            FROM stock_current sc
            JOIN products p ON p.id = sc.product_id
            LEFT JOIN locations l ON p.location_id = l.id
            LEFT JOIN stock s ON s.product_id = p.id
            LEFT JOIN quantity_units qu ON p.qu_id_stock = qu.id
            GROUP BY p.id
            ORDER BY l.name, p.name
        """)
        self._json(200, rows)

    def _api_mealplan(self, qs):
        today = date.today()
        # Default: this week (Mon-Sun)
        mon = today - timedelta(days=today.weekday())
        sun = mon + timedelta(days=6)
        d_from = qs.get("from", [mon.isoformat()])[0]
        d_to = qs.get("to", [sun.isoformat()])[0]

        rows = query_db(GROCY_DB, """
            SELECT mp.day, mp.section_id, mps.name as section_name,
                   r.id as recipe_id, r.name as recipe_name, r.description, r.base_servings
            FROM meal_plan mp
            LEFT JOIN meal_plan_sections mps ON mp.section_id = mps.id
            LEFT JOIN recipes r ON mp.recipe_id = r.id
            WHERE mp.day BETWEEN ? AND ?
            ORDER BY mp.day, mp.section_id
        """, (d_from, d_to))

        # Group by day
        days = {}
        for r in rows:
            d = r["day"]
            if d not in days:
                days[d] = []
            days[d].append(r)
        self._json(200, days)

    def _api_cooking_guide(self, qs):
        target = qs.get("date", [date.today().isoformat()])[0]

        rows = query_db(GROCY_DB, """
            SELECT mp.section_id, mps.name as section_name,
                   r.id as recipe_id, r.name as recipe_name,
                   r.description, r.base_servings, mp.recipe_servings
            FROM meal_plan mp
            LEFT JOIN meal_plan_sections mps ON mp.section_id = mps.id
            LEFT JOIN recipes r ON mp.recipe_id = r.id
            WHERE mp.day = ?
            ORDER BY mp.section_id
        """, (target,))

        # Parse each recipe
        guide = []
        seen = set()
        for r in rows:
            rid = r["recipe_id"]
            if rid in seen:
                continue
            seen.add(rid)
            parsed = parse_recipe_description(r.get("description", ""))

            # Auto-detect timers in steps
            steps_with_timers = []
            for step in (parsed["methods"][0]["steps"] if parsed["methods"] else []):
                timer = None
                tm = re.search(r"(\d+)\s*分", step)
                ts = re.search(r"(\d+)\s*秒", step)
                if tm:
                    timer = int(tm.group(1)) * 60
                elif ts:
                    timer = int(ts.group(1))
                steps_with_timers.append({"text": step, "timer_seconds": timer})

            guide.append({
                "recipe_id": rid,
                "recipe_name": r["recipe_name"],
                "section": r["section_name"],
                "servings": r["base_servings"],
                "title": parsed["title"],
                "ingredients": parsed["ingredients"],
                "steps": steps_with_timers,
                "storage": parsed["storage"],
            })

        self._json(200, {"date": target, "recipes": guide})

    def _api_deals(self, qs):
        q = qs.get("q", [""])[0]
        category = qs.get("category", ["ALL"])[0]
        limit = int(qs.get("limit", ["50"])[0])

        conditions = ["is_active = 1"]
        params = []

        if q:
            conditions.append("name LIKE ?")
            params.append(f"%{q}%")
        if category == "SEAFOOD":
            not_seafood = ('肉', '野菜', 'フルーツ', '塩干＆冷凍品', '惣菜＆デザート', 'その他')
            placeholders = ','.join('?' * len(not_seafood))
            conditions.append(f"category NOT IN ({placeholders})")
            params.extend(not_seafood)
        elif category and category != "ALL":
            conditions.append("category = ?")
            params.append(category)

        where = " AND ".join(conditions)
        rows = query_db(HACHI_DB, f"""
            SELECT name, category, price, unit, weight_kg, yield,
                   ROUND(price_per_edible_kg, 0) as price_per_edible_kg, url
            FROM items
            WHERE {where}
            ORDER BY CASE WHEN price_per_edible_kg IS NULL THEN 1 ELSE 0 END, price_per_edible_kg ASC
            LIMIT ?
        """, (*params, limit))
        self._json(200, rows)

    def _api_deals_categories(self):
        rows = query_db(HACHI_DB, """
            SELECT DISTINCT category, COUNT(*) as cnt
            FROM items WHERE is_active = 1
            GROUP BY category ORDER BY category
        """)
        # Add virtual "魚介" group (everything except 肉/野菜/フルーツ/塩干/惣菜/その他)
        not_seafood = {'肉', '野菜', 'フルーツ', '塩干＆冷凍品', '惣菜＆デザート', 'その他'}
        seafood_cnt = sum(r['cnt'] for r in rows if r['category'] not in not_seafood)
        result = [{'category': '★ 魚介（すべての魚・貝類）', 'value': 'SEAFOOD', 'cnt': seafood_cnt}]
        result.extend(rows)
        self._json(200, result)

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"

        # Security: prevent path traversal
        safe = os.path.normpath(path.lstrip("/"))
        if safe.startswith(".."):
            self._text(403, "Forbidden")
            return

        filepath = os.path.join(STATIC_DIR, safe)
        if not os.path.isfile(filepath):
            self._text(404, "Not Found")
            return

        mime, _ = mimetypes.guess_type(filepath)
        with open(filepath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ── POST ─────────────────────────────────────────────

    def do_POST(self):
        if self.path == "/ai":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            prompt = body.get("prompt", "")
            context = body.get("context", "")
            if not prompt:
                self._json(400, {"error": "prompt is required"})
                return

            system = (
                "あなたはキッチンアシスタントです。ユーザーは今まさに料理中です。\n"
                "Grocyの在庫・レシピ・献立を管理できます。\n\n"
                "【重要ルール】\n"
                "- 質問には今作っている料理の文脈で具体的に答えること。一般論は不要。\n"
                "- 「何mm？」「何分？」等には数字1つで即答し、理由は1文だけ。\n"
                "- 回答は音声読み上げ用に短く簡潔に。3文以内を目標とする。\n"
                "- マークダウンの装飾は使わず、プレーンテキストで返すこと。\n"
                "- 箇条書きや表は使わないこと。\n\n"
                "【食材制約ルール（最重要）】\n"
                "- レシピの変更や提案時、Grocyの在庫に存在する食材・調味料のみを使うこと。\n"
                "- 在庫にない食材は絶対に使わない。「一般家庭にあるだろう」と推測しない。\n"
                "- 在庫にない食材が必要な場合は、在庫内の代替品を提案するか、ユーザーに購入を確認する。\n"
                "- 在庫確認: sqlite3 /tmp/grocy.db \"SELECT p.name FROM stock_current sc JOIN products p ON p.id=sc.product_id;\"\n\n"
                f"{context}"
            )

            try:
                result = subprocess.run(
                    [
                        "claude", "-p",
                        "--system-prompt", system,
                        "--allowedTools", "Bash(docker cp *),Bash(sqlite3 *),Bash(curl *),Read,Grep,Glob",
                    ],
                    input=prompt,
                    capture_output=True, text=True, timeout=120,
                    cwd=WORK_DIR
                )
                response = result.stdout.strip() or result.stderr.strip() or "応答がありませんでした。"
                self._json(200, {"response": response})
            except subprocess.TimeoutExpired:
                self._json(504, {"error": "Claude Code がタイムアウトしました。"})
            except FileNotFoundError:
                self._json(500, {"error": "claude コマンドが見つかりません。"})
            except Exception as e:
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── Helpers ───────────────────────────────────────────

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code, msg):
        body = msg.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        print(f"[kitchen] {args[0]}")


if __name__ == "__main__":
    port = 8091
    print(f"[kitchen] Starting on http://localhost:{port}")
    print(f"[kitchen] Static dir: {STATIC_DIR}")
    print(f"[kitchen] Grocy DB: {GROCY_DB}")
    print(f"[kitchen] Hachi DB: {HACHI_DB}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
