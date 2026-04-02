# My Grocy - Claude Code 設定

## プロジェクト概要
Grocyベースの食材管理・レシピ計画システム。Docker Compose で運用。

## アーキテクチャ
- Grocy (PHP/SQLite): ポート9283
- MCP Grocy API (Node.js): ポート8080
- DB: コンテナ内 `/config/data/grocy.db`（ホストにマウント済み `./grocy-config:/config`）

## DB操作フロー
1. `docker cp grocy:/config/data/grocy.db /tmp/grocy.db` でコピー
2. `sqlite3 /tmp/grocy.db` で編集
3. `docker cp /tmp/grocy.db grocy:/config/data/grocy.db` でデプロイ

## 重要なテーブル
- `products`: 商品マスタ (location_id: 2=冷蔵庫, 3=冷凍庫)
- `stock` / `stock_current`: 在庫
- `stock_log`: 在庫変動ログ (user_id=1, transaction_type='purchase')
- `recipes` / `recipes_pos`: レシピとその材料
- `meal_plan` / `meal_plan_sections`: 献立 (section: 1=朝食, 2=昼食)
- `quantity_units`: 2=Piece, 3=Pack

## recipes_pos 挿入時の注意
- `only_check_single_unit_in_stock=1` を指定すること（qu_id変換トリガーのエラー回避）
- `qu_id` は省略可（トリガーが自動設定）

## meal_plan_sections
- section_id 1 = 昼食 (12:00)
- section_id 2 = 夕食 (19:00)

## Grocy API
- API Key: `.env` の `GROCY_APIKEY_VALUE` を使用
- 有効なキー: `c9dd381b58ad65962713351f2eeabf5e82034580793f8a93116843388d1dd250`（mcp用）
- エンドポイント: `http://localhost:9283/api`

## 八面六臂（業務用ネットスーパー）
- 商品DB: `/Users/ytonoyam/Dev/hachimenroppi/data/hachimenroppi.db`
- テーブル: `items` (name, category, price, unit, weight_kg, yield, price_per_edible_kg, is_active)
- 注文: 16時以降、翌日配達
- コスパ比較は `price_per_edible_kg`（可食部あたりkg単価）で行う

## 健康データ連携

### あすけん（栄養管理）
- 認証: `.env` の `ASKEN_EMAIL`, `ASKEN_PASSWORD`
- スクリプト: `asken-fetch.py`（データ取得）, `asken-record.py`（食事登録）
- 要件: `pip3 install playwright && python3 -m playwright install chromium`

### Health Planet（体重・体脂肪率 / TANITA）
- 認証: `.env` の `HP_CLIENT_ID`, `HP_CLIENT_SECRET`, `HP_USER`, `HP_PASSWORD`
- スクリプト: `healthplanet-fetch.py`
- OAuthトークンキャッシュ: `.healthplanet_token.json`（30日有効）

### 近隣スーパー特売（トクバイ）
- チラシは画像形式 → DL後にReadツールで画像認識
- 店舗ID: ジャパンミート(266712), コモディイイダ(7515), マミーマート(3639), ビッグ・エー(70801), フードガーデン(2605)

## Agent Skills (Slash Commands)
- `/recipe-plan`: 週間レシピ作成（一汁三菜・作り置き）
- `/stock-add`: 発注メール等から在庫追加
- `/stock-check`: 在庫一覧表示
- `/stock-update`: 在庫情報の更新
- `/stock-procurement`: 八面六臂から仕入れ調査（予算・栄養バランス考慮）
- `/nutrition-deals`: 栄養補強＋特売比較（八面六臂 vs 近隣スーパー）
- `/asken-sync`: Grocy献立→あすけん食事記録同期
- `/health-check`: 体重・体脂肪率・栄養評価の確認
- `/today-menu`: 今日の献立ガイド
