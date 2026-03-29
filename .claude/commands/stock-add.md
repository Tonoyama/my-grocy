# 在庫追加

発注メール、レシート、または自然言語入力からGrocyの在庫にアイテムを追加する。

## 手順

1. **DB取得**: `docker cp grocy:/config/data/grocy.db /tmp/grocy.db`

2. **入力解析**: ユーザーの入力（発注メール、レシート等）から以下を抽出する
   - 品名
   - 産地・メーカー
   - 数量
   - 価格（税抜）
   - 納品予定日

3. **既存商品チェック**: `SELECT id, name FROM products WHERE name LIKE '%キーワード%';` で既存商品と照合

4. **保管場所判定**: 冷蔵か冷凍か不明な場合はユーザーに確認する
   - location_id=2: 冷蔵庫
   - location_id=3: 冷凍庫

5. **DB投入**:
   ```sql
   -- 新規商品
   INSERT INTO products (name, location_id, qu_id_purchase, qu_id_stock, qu_id_consume)
   VALUES ('商品名', location_id, qu_id, qu_id, qu_id);
   -- qu_id: 2=Piece(個/枚/尾/切), 3=Pack(pc/袋/パック)

   -- 在庫
   INSERT INTO stock (product_id, amount, best_before_date, purchased_date, stock_id, price, location_id)
   VALUES (product_id, amount, 'YYYY-MM-DD', 'YYYY-MM-DD', hex(randomblob(16)), price, location_id);

   -- 在庫ログ
   INSERT INTO stock_log (product_id, amount, best_before_date, purchased_date, stock_id, transaction_type, price, location_id, user_id)
   VALUES (product_id, amount, 'YYYY-MM-DD', 'YYYY-MM-DD', (SELECT stock_id FROM stock WHERE product_id=X), 'purchase', price, location_id, 1);
   ```

6. **デプロイ**: `docker cp /tmp/grocy.db grocy:/config/data/grocy.db`

7. **確認**: 追加した商品の一覧を表示する

## 注意事項
- best_before_dateは納品日から1年後をデフォルトとする
- 既存商品と重複しないよう名前を確認する
- 価格がない場合は一般的な小売価格を設定し、ユーザーに確認する