# 今日の献立ガイド

今日の献立を表示し、作り置き済みの品は温め方、新規調理の品は作り方を案内する。

## 引数
- $ARGUMENTS: 対象の食事（例: 昼食, 夕食）。省略時は昼食・夕食の両方を表示

## 手順

1. **DBコピー**: `docker cp grocy:/config/data/grocy.db /tmp/grocy.db`

2. **今日の献立を取得**:
   ```sql
   SELECT mp.section_id, ms.name as section, r.id as recipe_id, r.name, r.description
   FROM meal_plan mp
   LEFT JOIN meal_plan_sections ms ON mp.section_id = ms.id
   LEFT JOIN recipes r ON mp.recipe_id = r.id
   WHERE mp.day = date('now', 'localtime')
   ORDER BY mp.section_id;
   ```
   - $ARGUMENTS が「昼食」なら section_id=1、「夕食」なら section_id=2 でフィルタする

3. **作り置き判定**: 以下の2つの条件で判定する

   **条件A: 過去の献立に同じレシピがある（前回提供済み）**
   ```sql
   SELECT DISTINCT mp_today.recipe_id, r.name, mp_past.day as cooked_on
   FROM meal_plan mp_today
   JOIN recipes r ON mp_today.recipe_id = r.id
   JOIN meal_plan mp_past ON mp_today.recipe_id = mp_past.recipe_id
     AND mp_past.day < mp_today.day
     AND mp_past.day >= date(mp_today.day, '-7 days')
   WHERE mp_today.day = date('now', 'localtime');
   ```

   **条件B: 日曜まとめ調理パターン（保存可能レシピ）**
   recipe-planでは日曜にまとめて調理する設計。今日が月曜以降の場合、
   レシピのdescriptionに「■ 保存」セクションがあるものは日曜に調理済みと判定する。
   ```sql
   -- 今日が日曜でなく、かつレシピに保存セクションがある = 作り置き済み
   SELECT r.id, r.name, r.description
   FROM meal_plan mp
   JOIN recipes r ON mp.recipe_id = r.id
   WHERE mp.day = date('now', 'localtime')
     AND strftime('%w', 'now', 'localtime') != '0'  -- 今日が日曜でない
     AND r.description LIKE '%■ 保存%';
   ```

   **判定ロジック:**
   - 条件Aに該当 → 作り置き（過去の献立で調理済み）
   - 条件Aに該当しないが条件Bに該当 → 作り置き（日曜まとめ調理済み）
   - どちらにも該当しない → 当日調理
   - ただし既製品（レンチンするだけ、パックから出すだけ等）は「簡単調理」として別枠表示

4. **在庫チェック**: 当日調理のレシピについて、材料の在庫を確認する
   ```sql
   SELECT r.name as recipe, p.name as ingredient, rp.amount, qu.name as unit,
     COALESCE(sc.amount, 0) as stock_amount
   FROM meal_plan mp
   JOIN recipes r ON mp.recipe_id = r.id
   JOIN recipes_pos rp ON rp.recipe_id = r.id
   JOIN products p ON rp.product_id = p.id
   LEFT JOIN quantity_units qu ON rp.qu_id = qu.id
   LEFT JOIN stock_current sc ON sc.product_id = rp.product_id
   WHERE mp.day = date('now', 'localtime');
   ```
   在庫が足りない材料があれば警告する。

5. **出力フォーマット**: 食事ごとに以下の形式で表示する

   ### {食事名}（昼食 / 夕食）

   **温めるだけ（作り置き済み）**
   作り置き済みの各品について:
   - 品名
   - レシピのdescriptionから「■ 保存」セクションの温め方を抽出して表示
   - 温め方が書かれていない場合は一般的な温め方を提案（汁物→鍋で弱火、炒め物→レンジ600W 1.5分、和え物→冷蔵のまま）

   **簡単調理（既製品・盛り付けのみ）**
   既製品やそのまま食べるものについて:
   - 品名と簡単な手順（レンチン、混ぜるだけ、切って盛るだけ等）

   **今日作るもの**
   当日調理の各品について:
   - 品名
   - レシピのdescriptionから「■ 作り方」セクションを抽出して簡潔に表示
   - 在庫不足の材料があれば警告

   **段取り**
   - 効率的な調理順を提案する（火を使うもの→レンジ→切るだけ→盛り付け）
   - 作り置きの温めタイミングも含める（食べる直前にまとめて温め等）