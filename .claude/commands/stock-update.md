# 在庫更新

既存の在庫情報（価格、保管場所、数量、商品名）を更新する。

## 手順

1. `docker cp grocy:/config/data/grocy.db /tmp/grocy.db`

2. 対象商品を検索:
   ```sql
   SELECT p.id, p.name, sc.amount, l.name as loc, s.price
   FROM stock_current sc
   JOIN products p ON p.id = sc.product_id
   LEFT JOIN locations l ON p.location_id = l.id
   LEFT JOIN stock s ON s.product_id = p.id
   WHERE p.name LIKE '%キーワード%'
   GROUP BY p.id;
   ```

3. 更新実行:
   - 価格更新: `UPDATE stock SET price = X WHERE product_id = Y;`
   - 保管場所変更: `UPDATE products SET location_id = X WHERE id = Y;` + `UPDATE stock SET location_id = X WHERE product_id = Y;`
   - 商品名変更: `UPDATE products SET name = 'X' WHERE id = Y;`
   - 数量変更: `UPDATE stock SET amount = X WHERE product_id = Y;`
   - stock_logも同時に更新する

4. `docker cp /tmp/grocy.db grocy:/config/data/grocy.db`