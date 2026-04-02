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
import threading
import uuid
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


_recipe_plan_status = {"running": False, "result": None}
_ai_tasks = {}  # {task_id: {"running": bool, "result": str|None, "choices": list|None}}


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
            elif path == "/api/ai/status":
                task_id = qs.get("id", [None])[0]
                if task_id and task_id in _ai_tasks:
                    self._json(200, _ai_tasks[task_id])
                else:
                    self._json(404, {"error": "task not found"})
            elif path == "/api/mealplan/validate":
                self._api_mealplan_validate(qs)
            elif path == "/api/recipe-plan/status":
                self._json(200, {
                    "running": _recipe_plan_status["running"],
                    "result": _recipe_plan_status["result"]
                })
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

    def _api_mealplan_validate(self, qs):
        """Validate meal plan against constraints: expiry, cost, effort."""
        today_str = date.today().isoformat()
        d_from = qs.get("from", [today_str])[0]
        d_to = qs.get("to", [(date.today() + timedelta(days=6)).isoformat()])[0]
        budget = int(qs.get("budget", ["1000"])[0])

        # Effort classification keywords
        EFFORT_ZERO = {"納豆", "プレーンヨーグルト", "ネーブルオレンジ"}
        EFFORT_REHEAT_KW = ["作り置き", "水煮", "レンチン", "レンジ", "トースター", "そのまま"]
        EFFORT_QUICK_KW = ["味噌汁", "スープ", "サラダ", "ナムル", "おひたし", "冷奴"]
        EFFORT_FRY_KW = ["フライ", "メンチカツ", "竜田揚げ", "揚げ"]

        def classify_effort(name, desc):
            if name in EFFORT_ZERO:
                return "zero"
            d = (desc or "").lower()
            if "低温調理" in name or "低温調理" in d:
                return "cook"
            if any(kw in name or kw in d for kw in EFFORT_REHEAT_KW):
                return "reheat"
            if any(kw in name for kw in EFFORT_FRY_KW):
                return "reheat"
            if any(kw in name for kw in EFFORT_QUICK_KW):
                return "quick"
            return "cook"

        EFFORT_LABELS = {
            "zero": "そのまま",
            "reheat": "温めるだけ",
            "passive": "放置調理",
            "quick": "5分以内",
            "cook": "要調理",
        }

        # Get meal plan with recipe + ingredient details
        meals = query_db(GROCY_DB, """
            SELECT mp.day, mp.section_id, mps.name as section_name,
                   r.id as recipe_id, r.name as recipe_name,
                   r.description, r.base_servings
            FROM meal_plan mp
            LEFT JOIN meal_plan_sections mps ON mp.section_id = mps.id
            LEFT JOIN recipes r ON mp.recipe_id = r.id
            WHERE mp.day BETWEEN ? AND ?
            ORDER BY mp.day, mp.section_id
        """, (d_from, d_to))

        # Get all recipe ingredients with stock info
        recipe_ids = list(set(m["recipe_id"] for m in meals if m["recipe_id"]))
        ingredients = []
        if recipe_ids:
            placeholders = ",".join("?" * len(recipe_ids))
            ingredients = query_db(GROCY_DB, f"""
                SELECT rp.recipe_id, rp.product_id, p.name as product_name,
                       rp.amount, r.base_servings,
                       s.price, s.best_before_date, p.location_id
                FROM recipes_pos rp
                JOIN products p ON rp.product_id = p.id
                JOIN recipes r ON rp.recipe_id = r.id
                LEFT JOIN stock s ON s.product_id = p.id
                WHERE rp.recipe_id IN ({placeholders})
                GROUP BY rp.recipe_id, rp.product_id
            """, recipe_ids)

        # Build ingredient lookup: recipe_id -> [{product, price, expiry, ...}]
        ing_by_recipe = {}
        for ing in ingredients:
            rid = ing["recipe_id"]
            if rid not in ing_by_recipe:
                ing_by_recipe[rid] = []
            ing_by_recipe[rid].append(ing)

        # Validate per day
        days = {}
        for m in meals:
            d = m["day"]
            if d not in days:
                days[d] = {"meals": [], "issues": [], "cost": 0, "effort_summary": {}}

            rid = m["recipe_id"]
            effort = classify_effort(m["recipe_name"] or "", m["description"] or "")

            meal_info = {
                "section": m["section_name"],
                "recipe": m["recipe_name"],
                "effort": effort,
                "effort_label": EFFORT_LABELS.get(effort, effort),
                "cost": 0,
                "expiry_issues": [],
            }

            # Check ingredients
            for ing in ing_by_recipe.get(rid, []):
                # Cost per serving (food items only, exclude seasonings loc=4)
                if ing["location_id"] != 4 and ing["price"]:
                    per_serving = round(ing["amount"] * ing["price"] / (ing["base_servings"] or 1))
                    meal_info["cost"] += per_serving

                # Expiry check
                if ing["best_before_date"] and ing["best_before_date"] < d:
                    meal_info["expiry_issues"].append({
                        "product": ing["product_name"],
                        "expiry": ing["best_before_date"],
                        "use_date": d,
                    })

            days[d]["meals"].append(meal_info)
            days[d]["cost"] += meal_info["cost"]

            # Effort summary
            eff = days[d]["effort_summary"]
            eff[effort] = eff.get(effort, 0) + 1

        # Build result with per-day issues
        result = []
        for d in sorted(days.keys()):
            info = days[d]
            issues = []

            # Cost check
            if info["cost"] > budget:
                issues.append({
                    "type": "cost",
                    "severity": "warning",
                    "message": f"予算超過: {info['cost']}円 (上限{budget}円)",
                })

            # Expiry issues
            for m in info["meals"]:
                for ei in m["expiry_issues"]:
                    issues.append({
                        "type": "expiry",
                        "severity": "error",
                        "message": f"期限切れ: {ei['product']} (期限{ei['expiry']}) を {ei['use_date']} に使用",
                    })

            # Effort check: count "cook" items
            cook_count = info["effort_summary"].get("cook", 0)
            if cook_count > 2:
                issues.append({
                    "type": "effort",
                    "severity": "warning",
                    "message": f"要調理が{cook_count}品あります",
                })

            result.append({
                "day": d,
                "cost": info["cost"],
                "budget": budget,
                "cost_ok": info["cost"] <= budget,
                "effort": info["effort_summary"],
                "effort_labels": {k: EFFORT_LABELS.get(k, k) for k in info["effort_summary"]},
                "meals": info["meals"],
                "issues": issues,
                "has_errors": any(i["severity"] == "error" for i in issues),
                "has_warnings": any(i["severity"] == "warning" for i in issues),
            })

        # Check unused expiring items
        unused_expiring = query_db(GROCY_DB, """
            SELECT p.id, p.name, sc.amount, s.best_before_date
            FROM stock_current sc
            JOIN products p ON p.id = sc.product_id
            LEFT JOIN stock s ON s.product_id = p.id
            WHERE p.location_id IN (2, 3)
            AND s.best_before_date <= ?
            AND s.best_before_date >= ?
            AND p.id NOT IN (
                SELECT DISTINCT rp.product_id FROM meal_plan mp
                JOIN recipes_pos rp ON rp.recipe_id = mp.recipe_id
                WHERE mp.day BETWEEN ? AND ?
            )
            GROUP BY p.id
            ORDER BY s.best_before_date
        """, (d_to, d_from, d_from, d_to))

        self._json(200, {
            "from": d_from,
            "to": d_to,
            "budget": budget,
            "days": result,
            "unused_expiring": unused_expiring,
        })

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
            history = body.get("history", [])  # [{role: "user"/"ai", text: "..."}]
            if not prompt:
                self._json(400, {"error": "prompt is required"})
                return

            system = (
                "あなたはキッチンアシスタントです。Grocyの在庫・レシピ・献立を管理できます。\n\n"
                "【重要ルール】\n"
                "- ユーザーの依頼には即座に実行すること。確認が必要な場合のみ質問する。\n"
                "- 在庫の追加・削除・更新はツールを使って実際にDBを操作すること。\n"
                "- 操作後は結果を簡潔に報告する（例: 「小松菜 1袋 200円で冷蔵庫に登録しました」）。\n"
                "- 回答は簡潔に。3文以内を目標とする。\n"
                "- マークダウンの装飾は使わず、プレーンテキストで返すこと。\n"
                "- ユーザーに選択を求める場合、質問文の最後に以下のJSON形式で選択肢を追加すること:\n"
                "  [CHOICES:{\"choices\":[\"選択肢1\",\"選択肢2\",\"選択肢3\"]}]\n"
                "  例: 冷蔵庫と冷凍庫、どちらに保存しますか？[CHOICES:{\"choices\":[\"冷蔵庫\",\"冷凍庫\"]}]\n"
                "  例: 既存の献立を削除して作り直しますか？[CHOICES:{\"choices\":[\"作り直す\",\"追加だけ\",\"キャンセル\"]}]\n\n"
                "【DB操作手順】\n"
                "- 操作前: docker cp grocy:/config/data/grocy.db /tmp/grocy.db\n"
                "- 操作後: docker cp /tmp/grocy.db grocy:/config/data/grocy.db\n"
                "- 在庫確認: sqlite3 /tmp/grocy.db \"SELECT p.id,p.name,sc.amount,qu.name FROM stock_current sc JOIN products p ON p.id=sc.product_id LEFT JOIN quantity_units qu ON p.qu_id_stock=qu.id;\"\n"
                "- 新規商品登録時: products, stock, stock_log テーブルに挿入\n"
                "- location_id: 2=冷蔵庫, 3=冷凍庫, 4=調味料\n"
                "- qu_id: 2=Piece, 3=Pack, 4=g, 5=個, 6=本, 7=枚, 8=切, 9=尾, 10=袋, 11=丁, 12=パック\n"
                "- stock挿入時: stock_id=hex(randomblob(16)), transaction_type='purchase', user_id=1\n\n"
                f"{context}"
            )

            # Build full prompt with conversation history
            full_prompt = ""
            for msg in history:
                role = "ユーザー" if msg.get("role") == "user" else "アシスタント"
                full_prompt += f"[{role}]: {msg.get('text', '')}\n"
            full_prompt += f"[ユーザー]: {prompt}"

            task_id = str(uuid.uuid4())
            _ai_tasks[task_id] = {"running": True, "result": None, "choices": None}

            def run_ai():
                try:
                    result = subprocess.run(
                        [
                            "claude", "-p",
                            "--system-prompt", system,
                            "--allowedTools", "Bash(docker cp *),Bash(sqlite3 *),Bash(curl *),Read,Grep,Glob",
                        ],
                        input=full_prompt,
                        capture_output=True, text=True, timeout=600,
                        cwd=WORK_DIR
                    )
                    response = result.stdout.strip() or result.stderr.strip() or "応答がありませんでした。"
                    choices = None
                    choice_match = re.search(r'\[CHOICES:(\{.*?\})\]', response)
                    if choice_match:
                        try:
                            choices = json.loads(choice_match.group(1)).get("choices", [])
                        except: pass
                        response = response[:choice_match.start()].strip()
                    _ai_tasks[task_id]["result"] = response
                    _ai_tasks[task_id]["choices"] = choices
                except subprocess.TimeoutExpired:
                    _ai_tasks[task_id]["result"] = "タイムアウトしました（10分）。もう少し具体的に指示してみてください。"
                except FileNotFoundError:
                    _ai_tasks[task_id]["result"] = "claude コマンドが見つかりません。"
                except Exception as e:
                    _ai_tasks[task_id]["result"] = str(e)
                finally:
                    _ai_tasks[task_id]["running"] = False

            threading.Thread(target=run_ai, daemon=True).start()
            self._json(202, {"task_id": task_id})
        elif self.path == "/api/recipe-plan":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            week = body.get("week", "今週月〜日")
            # Run in background thread
            def run_plan():
                _recipe_plan_status["running"] = True
                _recipe_plan_status["result"] = None
                try:
                    result = subprocess.run(
                        ["claude", "-p", "--allowedTools",
                         "Bash,Read,Write,Edit,Glob,Grep"],
                        input=f"/recipe-plan {week}",
                        capture_output=True, text=True, timeout=600,
                        cwd=WORK_DIR
                    )
                    _recipe_plan_status["result"] = result.stdout.strip() or result.stderr.strip() or "完了しました"
                except subprocess.TimeoutExpired:
                    _recipe_plan_status["result"] = "タイムアウトしました（10分）"
                except Exception as e:
                    _recipe_plan_status["result"] = str(e)
                finally:
                    _recipe_plan_status["running"] = False
            if _recipe_plan_status.get("running"):
                self._json(409, {"error": "献立作成が既に実行中です"})
            else:
                threading.Thread(target=run_plan, daemon=True).start()
                self._json(202, {"message": "献立作成を開始しました"})
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
