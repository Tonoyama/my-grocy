# 栄養補強 特売比較

献立の栄養バランスを分析し、不足があれば八面六臂と近隣スーパーの特売を比較して最安の補強案を提案する。

## 手順

### 1. 体組成・健康データ取得

最新の体重・体脂肪率を取得し、栄養分析の参考にする:
```bash
python3 /Users/ytonoyam/Dev/my-grocy/healthplanet-fetch.py --days 14
```

あすけんに食事記録があれば、実際の栄養摂取状況も確認:
```bash
python3 /Users/ytonoyam/Dev/my-grocy/asken-fetch.py --week
```
スクリーンショット (`/tmp/asken_*.png`) を Read ツールで画像読み取りして栄養データを抽出する。

### 2. 献立と在庫の確認

```bash
docker cp grocy:/config/data/grocy.db /tmp/grocy.db
```

```sql
-- 在庫一覧
SELECT p.id, p.name, sc.amount, l.name as loc, s.price
FROM stock_current sc JOIN products p ON p.id=sc.product_id
LEFT JOIN locations l ON p.location_id=l.id
LEFT JOIN stock s ON s.product_id=p.id
WHERE p.location_id <> 4
GROUP BY p.id ORDER BY l.name, s.best_before_date;

-- 今週の献立
SELECT mp.day, ms.name, r.name, r.description FROM meal_plan mp
JOIN recipes r ON r.id=mp.recipe_id
JOIN meal_plan_sections ms ON ms.id=mp.section_id
WHERE mp.day >= date('now')
ORDER BY mp.day, mp.section_id;
```

### 3. 栄養分析

献立の食材から、1日あたりの栄養バランスを推定する。以下の栄養素について不足を判定:

| 栄養素 | 目安(1日) | 代表食材 |
|--------|----------|----------|
| たんぱく質 | 60g | 肉・魚・卵・豆腐 |
| ビタミンC | 100mg | 緑黄色野菜・果物 |
| 食物繊維 | 20g | 根菜・きのこ・海藻 |
| カルシウム | 650mg | 小魚・乳製品・小松菜 |
| 鉄分 | 7mg | レバー・貝類・ほうれん草 |
| βカロテン | 3000μg | にんじん・かぼちゃ・ほうれん草 |
| DHA/EPA | 1g | 青魚（さば・いわし・さんま） |

不足がなければ「栄養バランス良好、追加購入不要」と報告して終了。

### 4. 八面六臂の最新データ取得

```bash
cd /Users/ytonoyam/Dev/hachimenroppi && make run-now
```

スクレイピング完了後、不足栄養素を補える食材を検索:

```sql
-- 八面六臂DB: /Users/ytonoyam/Dev/hachimenroppi/data/hachimenroppi.db
SELECT name, category, price, unit, weight_kg,
       ROUND(price_per_edible_kg, 0) as edible_kg_price, url
FROM items
WHERE is_active = 1 AND price_per_edible_kg IS NOT NULL
  AND (name LIKE '%キーワード%' OR category = 'カテゴリ')
ORDER BY price_per_edible_kg ASC
LIMIT 10;
```

### 5. 近隣スーパーの特売チラシ取得

トクバイ（tokubai.co.jp）から以下の食品スーパーのチラシ画像をダウンロードして読み取る。

**対象店舗:**
| 店舗 | トクバイ店舗ID | トクバイURL名 |
|------|---------------|-------------|
| ジャパンミート卸売市場 東川口店 | 266712 | %E3%82%B8%E3%83%A3%E3%83%91%E3%83%B3%E3%83%9F%E3%83%BC%E3%83%88%E5%8D%B8%E5%A3%B2%E5%B8%82%E5%A0%B4 |
| コモディイイダ 東川口店 | 7515 | %E3%82%B3%E3%83%A2%E3%83%87%E3%82%A3%E3%82%A4%E3%82%A4%E3%83%80 |
| マミーマート 川口安行店 | 3639 | %E3%83%9E%E3%83%9F%E3%83%BC%E3%83%9E%E3%83%BC%E3%83%88 |
| ビッグ・エー 川口戸塚店 | 70801 | %E3%83%93%E3%83%83%E3%82%B0%E3%83%BB%E3%82%A8%E3%83%BC |
| 与野フードセンター フードガーデン戸塚安行駅店 | 2605 | %E4%B8%8E%E9%87%8E%E3%83%95%E3%83%BC%E3%83%89%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC |

**チラシ取得手順:**

1. 店舗ページからチラシ画像URLを取得:
   ```
   WebFetch: https://tokubai.co.jp/{トクバイURL名}/{店舗ID}
   → HTMLから image.tokubai.co.jp/images/bargain_office_leaflets/ の画像URLを抽出
   ```
   チラシ一覧ページ（複数チラシがある場合）:
   ```
   WebFetch: https://tokubai.co.jp/{トクバイURL名}/{店舗ID}/leaflets
   → 各チラシのリーフレットIDを取得し、個別ページから画像URLを抽出
   ```

2. オリジナルサイズの画像をダウンロード:
   - サムネイルURL `w=180,h=135,c=true/XXXXX.jpg` → `o=true/XXXXX.jpg` に変換
   ```bash
   curl -sL -o /tmp/leaflet_{店舗}_{N}.jpg "{画像URL}"
   ```

3. Read ツールで画像を読み取り、商品名と価格をテキスト化

### 6. 価格比較

不足栄養素を補える食材について、3ソースで価格比較表を作成:

| 食材 | 栄養素 | 八面六臂 | スーパー特売 | 現在庫価格 | 最安 |
|------|--------|----------|------------|-----------|------|
| ほうれん草 | ビタミンC,鉄 | 200円/袋 | 99円(ジャパンミート) | 178円 | スーパー |
| 小松菜 | カルシウム | 150円/袋 | 79円(ジャパンミート) | - | スーパー |

比較のポイント:
- 八面六臂は `price_per_edible_kg`（可食部kg単価）で比較
- スーパーは表示価格/推定重量で概算kg単価を計算
- 配達コスト考慮: 八面六臂は翌日配達（送料込み）、スーパーは即日入手可能

### 7. 提案

以下の形式で提案を出力:

```
## 栄養分析結果
- 不足: ビタミンC（緑黄色野菜が少ない）
- 不足: 食物繊維（根菜・きのこなし）

## 購入提案
### 八面六臂（翌日配達）
| 商品 | 価格 | 数量 | URL | 用途 |
|------|------|------|-----|------|
| ... | ... | ... | ... | ... |

### スーパー特売（即日入手）
| 商品 | 価格 | 店舗 | チラシ期間 | 用途 |
|------|------|------|-----------|------|
| ... | ... | ... | ... | ... |

## 推奨
(最安の組み合わせ + 献立への組み込み方を提案)
```

### 8. ユーザーが承認したら在庫に追加

`/stock-add` スキルを使って Grocy に登録する。

## 注意事項
- 八面六臂のスクレイピングは `make run-now` で最新化（1-2分かかる）
- トクバイのチラシは画像形式なので、Read ツールで画像認識して読み取る
- チラシの掲載期間を確認し、期限切れのセールは除外する
- 栄養不足がない場合は「購入不要」と明確に伝える
- 予算(週7,500円)の残りを超える提案はしない