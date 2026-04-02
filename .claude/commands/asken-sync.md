# あすけん食事記録同期

Grocyの献立(実食記録)をあすけんに自動同期し、栄養評価を取得する。

## 前提
- Playwright (Python): `pip3 install playwright && python3 -m playwright install chromium`
- 認証情報: `.env` に `ASKEN_EMAIL`, `ASKEN_PASSWORD` を設定
- スクリプト:
  - `asken-fetch.py` — あすけんからデータ取得
  - `asken-record.py` — あすけんに食事登録

## 手順

### 1. Grocyから実食記録を取得
```bash
docker cp grocy:/config/data/grocy.db /tmp/grocy.db
```
```sql
SELECT mp.day, mps.name as meal,
       GROUP_CONCAT(r.name, ', ') as items
FROM meal_plan mp
JOIN recipes r ON mp.recipe_id = r.id
JOIN meal_plan_sections mps ON mp.section_id = mps.id
WHERE mp.day = '{対象日}'
GROUP BY mp.day, mp.section_id
ORDER BY mp.section_id;
```

### 2. あすけんに食事を登録

Playwrightでログイン→検索→登録のフローを実行する。

#### ログイン
```python
page.goto("https://www.asken.jp/login", wait_until="domcontentloaded")
page.fill("#CustomerMemberEmail", EMAIL)
page.fill("#CustomerMemberPasswdPlain", PASSWORD)
page.click("#SubmitSubmit")
```

#### 食品検索→選択→量設定→登録
```python
# meal_type: breakfast/lunch/dinner/sweets
page.goto(f"https://www.asken.jp/wsp/meal/{meal_type}/{date}", wait_until="domcontentloaded")

# 検索
page.fill("#search_input", search_term)
page.press("#search_input", "Enter")
# 3秒待機

# 最初の結果をクリック
page.locator('a[onclick*="choseMenuBySearch"]').first.click(force=True)
# 2秒待機

# 量を設定 (1=1人前, 0.5=半人前, 2=2人前)
page.evaluate(f'V2WspMeal.step3.choseQuantity("{quantity}")')

# /meal/add_menu APIで登録
page.evaluate(f"""
    (async () => {{
        var form = document.getElementById('step3_form');
        var fd = new URLSearchParams(new FormData(form));
        var resp = await fetch('/meal/add_menu?meal_type={meal_type}&record_date={date}', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest'}},
            body: fd.toString()
        }});
        return await resp.json();
    }})()
""")
```

#### 「食べなかった」を登録
```python
page.goto(f"https://www.asken.jp/wsp/comment?date={date}", wait_until="domcontentloaded")
page.evaluate(f"V2WspMeal.noeat('{meal_type}')")  # breakfast/lunch/dinner/sweets/exercise
```

#### 食品を削除
```python
# ページHTMLから delete_meal IDを特定
# HTML内で delete_meal('xxx') の前後500文字に商品名が含まれる
page.evaluate(f"""
    (async () => {{
        var resp = await fetch('/meal/delete_menu/{meal_id}?meal_type={meal_type}&record_date={date}', {{
            method: 'POST',
            headers: {{'X-Requested-With': 'XMLHttpRequest'}}
        }});
        return await resp.json();
    }})()
""")
```

### 3. 白米の登録
全食事に白米0.5合を追加する場合:
- 検索: 「ごはん」→「ご飯(白ごはん180g)」を選択（0.5合≈180g≈281kcal）
- 量: 1杯

### 4. 栄養評価を取得

#### 全日アドバイス（全食事登録後）
```
URL: https://www.asken.jp/wsp/advice/YYYY-MM-DD
```
中間評価（昼食後など）は `/wsp/advice/YYYY-MM-DD/4`

#### 取得できるデータ
- エネルギー、たんぱく質、脂質、炭水化物
- カルシウム、鉄、ビタミンA/E/B1/B2/C
- 食物繊維、飽和脂肪酸、塩分
- 不足栄養素に対する推奨食材
- 食事バランスガイド判定

### 5. あすけんの食品名マッピング

Grocyのレシピ名 → あすけん検索キーワードのマッピング例:
| Grocyレシピ | あすけん検索 | 補足 |
|------------|------------|------|
| 鶏だんご豚汁 | 豚汁 | |
| いわしの生姜煮 | いわし 生姜煮 | |
| エゾアワビの酒蒸し | あわび | |
| もやしのナムル/ごまナムル | もやしナムル | |
| ほうれん草のおひたし | ほうれん草 おひたし | |
| 鮭の味噌焼き | 鮭 味噌焼き | |
| 金目鯛の煮付け | 金目鯛 煮付け | |
| マコガレイ刺身 | カレイ | 刺身がなければ近似 |
| 豚ハツのネギ塩炒め | 豚ハツ | |
| 乾麺50g | そうめん → 1/2人前 | |
| 白米0.5合 | ごはん → ご飯(白ごはん180g) 1杯 | |

## 注意事項
- あすけんはSPA的な構造のため、`choseQuantity` はUI更新のみ。実際の登録は `/meal/add_menu` APIをfetchで叩く必要がある
- 各食品追加後はページをリロードしてから次の食品を追加する（step3_formが上書きされるため）
- 削除は `/meal/delete_menu/{id}` APIを直接叩く（`V2WspMeal.delete_meal()` はheadlessで不安定）
- 検索結果の1件目が必ずしも正しいとは限らない。近い名前を優先的に選ぶこと