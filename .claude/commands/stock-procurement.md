# 八面六臂 仕入れ調査

予算に余裕がある場合に、八面六臂（業務用ネットスーパー）から栄養バランスや献立の補強に最適な商品を調査・提案する。予算に十分な余裕がある場合は、スーパーでは手が出にくい高級食材をコスパ良く楽しむ提案も行う。

## 前提条件
- 注文: 当日16時以降に可能（生鮮品）
- 配達: 基本翌日着
- データベース: `/Users/ytonoyam/Dev/hachimenroppi/data/hachimenroppi.db`

## 手順

1. **現在の在庫と献立を確認**
   ```bash
   docker cp grocy:/config/data/grocy.db /tmp/grocy.db
   ```
   ```sql
   -- 在庫
   SELECT p.name, sc.amount, l.name as loc, s.price
   FROM stock_current sc JOIN products p ON p.id=sc.product_id
   LEFT JOIN locations l ON p.location_id=l.id
   LEFT JOIN stock s ON s.product_id=p.id
   GROUP BY p.id ORDER BY l.name, p.name;

   -- 献立
   SELECT mp.day, ms.name, r.name FROM meal_plan mp
   JOIN recipes r ON r.id=mp.recipe_id
   JOIN meal_plan_sections ms ON ms.id=mp.section_id
   ORDER BY mp.day, mp.section_id;
   ```

2. **予算の残りを計算**
   - 週予算7,500円 − 現在の献立食材コスト = 残予算
   - 米の値段は含めない

3. **栄養バランスの課題を分析**
   主に以下の不足を確認する:
   - ビタミンC（緑黄色野菜の不足）
   - 食物繊維（根菜・きのこの不足）
   - カルシウム（小魚・乳製品の不足）
   - βカロテン/ビタミンA（にんじん等の不足）
   - 鉄分（レバー・小魚・貝類の不足）
   - DHA/EPA（青魚の不足）

4. **八面六臂のDBから候補を検索**

   ### 栄養補強（必須検索）
   ```sql
   -- 野菜（ビタミン・食物繊維）
   SELECT name, price, unit, weight_kg, url FROM items
   WHERE category='野菜' AND is_active=1 AND price <= 200
   ORDER BY price_per_edible_kg ASC;

   -- 塩干・冷凍品（保存がきく）
   SELECT name, price, unit, weight_kg, url FROM items
   WHERE category='塩干＆冷凍品' AND is_active=1 AND price <= 200
   ORDER BY price_per_edible_kg ASC;

   -- 惣菜（副菜追加用）
   SELECT name, price, unit, weight_kg, url FROM items
   WHERE category='惣菜＆デザート' AND is_active=1 AND price <= 100
   ORDER BY price ASC;

   -- キーワード検索
   SELECT name, category, price, unit, weight_kg, url FROM items
   WHERE is_active=1 AND price <= 300
   AND (name LIKE '%キーワード%')
   ORDER BY price;
   ```

   ### 高級食材（予算に余裕がある場合のみ）
   予算残が十分ある場合、スーパーでは割高だが八面六臂なら業務用卸価格で手に入る高級食材を提案する。
   「スーパー相場の50〜70%以下で買える」ものが狙い目。

   ```sql
   -- 高級食材コスパランキング（可食部kg単価で比較）
   -- ウニ、生カキ、ホタテ、本マグロ、和牛、馬刺し等
   SELECT name, category, price, unit, weight_kg,
          ROUND(price_per_edible_kg,0) as edible_kg_price, url
   FROM items
   WHERE is_active=1
   AND (category IN ('ウニ','カキ','ホタテ','マグロ')
     OR name LIKE '%A5%' OR name LIKE '%黒毛和牛%'
     OR name LIKE '%馬刺し%' OR name LIKE '%フォアグラ%'
     OR name LIKE '%中トロ%' OR name LIKE '%大トロ%')
   AND price <= {残予算}
   ORDER BY price_per_edible_kg ASC;
   ```

   **高級食材のスーパー相場目安（参考）:**
   | 食材 | スーパー相場 | 八面六臂で狙える価格帯 |
   |------|------------|---------------------|
   | 生ウニ | 3,000〜5,000円/100g | 520円/40g (13,000円/kg) |
   | 生カキ | 300〜500円/個 | 120〜350円/個 |
   | 殻付きホタテ | 400〜600円/枚 | 440〜750円/枚 |
   | 本マグロ赤身 | 3,000〜5,000円/kg | ヒレ肉 1,210円/kg |
   | 黒毛和牛ステーキ | 5,000〜8,000円/100g | モモ 470〜780円/80-100g |
   | 馬刺し | 5,000〜8,000円/kg | 335円/50g (6,700円/kg) |
   | 黒毛和牛ハンバーグ | 500〜800円/個 | 350円/個 |

5. **提案を作成**
   提案は以下の形式で表示する:

   | 商品 | 価格 | 数量 | 注文URL | 栄養/用途 |
   |------|------|------|---------|-----------|
   | 商品名 | ○○円/unit | N個 | https://hachimenroppi.com/detail/XXXXX/ | 説明 |

   - 合計金額が残予算内に収まることを確認
   - 配達日を明記（注文翌日）
   - 献立への組み込み方を提案
   - 高級食材は「ご褒美枠」として栄養補強と分けて提示

6. **ユーザーが承認したら在庫に追加**
   `/stock-add` スキルを使って Grocy に登録する

## データベーススキーマ（八面六臂）

```sql
-- items テーブル
-- id, name, url, category, origin, price, unit, weight_kg,
-- processing_state, yield, price_per_edible_kg, is_active, scraped_at
--
-- カテゴリ一覧:
-- 野菜, 肉, フルーツ, 塩干＆冷凍品, 惣菜＆デザート,
-- マグロ, タイ, ブリ, カキ, アジ, イカ, サバ, その他, etc.
--
-- yield: 可食部割合（0.0〜1.0）
-- price_per_edible_kg: 可食部あたりのkg単価
-- url: 商品ページURL（https://hachimenroppi.com/detail/XXXXX/）
```

## 注意事項
- 八面六臂は業務用食材の卸売サイト（hachimenroppi.com）
- 価格は税抜表示
- 生鮮品は16時以降注文、翌日配達
- DBのデータは毎日スクレイピングで更新される（最新でない場合あり）
- 可食部単価(price_per_edible_kg)でコスパ比較するのが重要
- 提案時は必ず注文URL（https://hachimenroppi.com/detail/XXXXX/）を含めること
- 高級食材はスーパー相場と比較して明らかにお得な場合のみ提案する