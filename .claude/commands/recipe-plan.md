# 週間レシピ作成 (一汁三菜 作り置き)

Grocyの在庫データベースをもとに、1週間分の作り置きレシピと献立を作成する。

## 手順

1. **体組成データ取得**: 最新の体重・体脂肪率を取得し、カロリー目標の調整に使う
   ```bash
   python3 /Users/ytonoyam/Dev/my-grocy/healthplanet-fetch.py --days 14
   ```
   - 体重が増加傾向ならカロリー控えめに、減少傾向なら維持を意識
   - あすけんに食事記録があれば栄養バランスの偏りも確認:
   ```bash
   python3 /Users/ytonoyam/Dev/my-grocy/asken-fetch.py --week
   ```

2. **在庫取得**: `docker cp grocy:/config/data/grocy.db /tmp/grocy.db` でDBをコピーし、`sqlite3 /tmp/grocy.db` で現在の在庫を確認する
   ```sql
   SELECT p.id, p.name, sc.amount, l.name as loc, s.price
   FROM stock_current sc JOIN products p ON p.id=sc.product_id
   LEFT JOIN locations l ON p.location_id=l.id
   LEFT JOIN stock s ON s.product_id=p.id
   GROUP BY p.id ORDER BY l.name, p.name;
   ```

2. **制約確認**: ユーザーに以下を確認する
   - 期間（デフォルト: 来週月〜日）
   - 予算（デフォルト: 7,500円、米は除外）
   - カロリー上限（デフォルト: 1日1,500kcal）
   - 食事回数（デフォルト: 昼食+夕食）
   - 冷蔵品の消費期限優先度

3. **在庫にある食材・調味料の一覧を作成**
   レシピ設計の前に、使用可能な食材と調味料を明確にする。
   **在庫に存在しない食材・調味料はレシピに絶対に使わないこと。**
   ```sql
   -- 在庫にある全商品リスト
   SELECT p.name FROM stock_current sc
   JOIN products p ON p.id=sc.product_id;
   ```
   この一覧を「使用可能食材リスト」として、以降のレシピ設計で厳守する。

4. **レシピ設計**: 以下のルールで献立を作成する
   - 一汁三菜（汁物1品+主菜+副菜2品）を基本とする
   - 冷蔵庫の生鮮品（海鮮・肉・野菜）を週前半に優先消費
   - 冷凍品は週後半に使用
   - 日曜日にまとめて調理し、冷凍保存（作り置き）
   - 調味料は予算に含めない

   ### 【最重要】食材制約ルール
   - **在庫に存在する食材・調味料のみ**を使ってレシピを考える
   - サラダ油、ごま油、バター、オリーブオイル等の油脂類も在庫になければ使用不可
   - 砂糖、みりん、片栗粉等の基本調味料も在庫確認が必須
   - 「一般家庭にあるだろう」という推測で食材を使わない
   - 在庫にない食材が必要な場合は、ユーザーに確認するか、在庫内の代替品で対応する
   - レシピの各材料が在庫にあるか1つずつ検証してから確定する

5. **食材検証**: レシピ確定前に、全レシピの全材料を在庫と突合する
   ```sql
   -- レシピで使う材料が在庫に存在するか確認
   -- 在庫にない食材が1つでもあればレシピを修正する
   ```
   在庫にない食材が見つかった場合:
   - まず在庫内の代替品で置き換えられるか検討する
   - 代替不可能な場合はユーザーに「購入が必要」と報告する
   - ユーザーが購入しない場合はレシピ自体を変更する

6. **DB投入**: レシピ・材料・献立をGrocyのDBに投入する
   - `recipes` テーブルにレシピ名・説明・人数を登録
   - `recipes_pos` テーブルに材料を登録（`only_check_single_unit_in_stock=1` を使用してqu_idの変換エラーを回避）
   - `meal_plan` テーブルに日別の献立を登録
   - `meal_plan_sections` に昼食(sort_number=1)・夕食(sort_number=2)が必要
   - 投入後 `docker cp /tmp/grocy.db grocy:/config/data/grocy.db` でデプロイ

7. **サマリー出力**: 以下をユーザーに表示する
   - 日別献立表（昼食・夕食）
   - 食材使用一覧と残在庫
   - 合計コストとカロリー
   - 作り置き調理スケジュール

## テーブルスキーマ参考

```sql
-- recipes: id, name, description, base_servings
-- recipes_pos: recipe_id, product_id, amount, ingredient_group, only_check_single_unit_in_stock
-- meal_plan: day(DATE), type('recipe'), recipe_id, recipe_servings, section_id
-- meal_plan_sections: name, sort_number, time_info
-- products: id, name, location_id, qu_id_purchase, qu_id_stock
-- stock_current: product_id, amount, best_before_date
-- locations: id=2 冷蔵庫, id=3 冷凍庫
-- quantity_units: id=2 Piece, id=3 Pack
```