#!/usr/bin/env python3
"""Voice-to-Claude bridge server.
Receives voice commands via HTTP POST and routes them to Claude Code CLI.
"""
import subprocess
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):
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

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        print(f"[voice-server] {args[0]}")

if __name__ == "__main__":
    port = 8091
    print(f"[voice-server] Starting on http://localhost:{port}")
    print(f"[voice-server] Working directory: {WORK_DIR}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
