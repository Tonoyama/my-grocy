# Grocy 日本語登録（OpenAI + MCP）

このドキュメントは、自然言語（日本語）で Grocy に品目を登録する手順です。

## 前提

- Docker が使えること
- Node.js 18+ がローカルにあること
- `.env` に以下が設定済み
  - `GROCY_APIKEY_VALUE`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`（任意）
  - `MCP_HTTP_URL`（通常は `http://localhost:8080/mcp`）

## 起動

MCP サーバーは `docker compose up -d` で起動します。  
自然言語登録は **別コマンド** で実行します（常駐プロセスではありません）。

```bash
docker compose up -d
```

## 使い方（簡単）

ルートのスクリプトを実行してください（`.env` を自動で読み込みます）。

```bash
./nl-register.sh "牛乳 2本 2024-12-31 198円"
```

`--dry-run` を付けると Grocy への書き込みは行いません。

```bash
./nl-register.sh --dry-run "醤油 1本 2025-01-10 398円"
```

## 直接実行する場合

```bash
set -a && source .env && set +a
node mcp-grocy-api/scripts/nl-register.mjs "牛乳 2本 2024-12-31 198円"
```

## よくある入力例

```text
卵 1パック 2025-01-05 258円
ヨーグルト 3個 2024-12-20 450円
買い物リストに トマト 2個
在庫を 牛乳 3本 にする
```

## 注意点

- 「円/¥」の価格は JPY として扱われます。
- 物品が未登録の場合は自動で作成されます。
- `docker compose up -d` だけでは登録処理は走りません。

## トラブルシュート

- `401 Unauthorized` → `.env` の `GROCY_APIKEY_VALUE` を確認
- `MCP request failed` → `mcp-grocy-api` が起動しているか確認
- `ECONNREFUSED` → `MCP_HTTP_URL` のポート/URLを確認
