# 在庫確認

Grocyの現在の在庫を一覧表示する。

## 手順

1. `docker cp grocy:/config/data/grocy.db /tmp/grocy.db`

2. 在庫クエリ:
   ```sql
   SELECT p.id, p.name, sc.amount, l.name as loc, s.price,
          sc.best_before_date
   FROM stock_current sc
   JOIN products p ON p.id = sc.product_id
   LEFT JOIN locations l ON p.location_id = l.id
   LEFT JOIN stock s ON s.product_id = p.id
   GROUP BY p.id
   ORDER BY l.name, p.name;
   ```

3. 保管場所別（冷凍庫/冷蔵庫）に整理して表形式で表示する

4. 価格が未設定の商品があれば警告する

5. 合計金額を計算して表示する