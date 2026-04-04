# マネーフォワード家計確認

マネーフォワードMEから月間収支・口座残高・支出内訳を取得して報告する。

## 前提
- Playwright (Python): `pip3 install playwright && python3 -m playwright install chromium`
- 永続Chromeプロファイル: `~/.mf_chrome_profile`
- 初回のみブラウザが開くので手動でGoogleログイン+2FAを行う
- headful必須（headlessはForbidden）

## 認証・接続

```python
from playwright.sync_api import sync_playwright
import os

PROFILE_DIR = os.path.expanduser("~/.mf_chrome_profile")

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")
```

**重要**: `add_init_script` でwebdriver検知を回避すること。

## 手順

### 1. ホーム — 総資産・口座残高
```
URL: https://moneyforward.com/
```
取得項目:
- 総資産
- 各銀行口座残高（伊予銀行、住信SBI、PayPay銀行、三井住友信託）
- カード利用残高
- 当月収支サマリー
- 直近の入出金

### 2. 家計簿 — 当月の入出金明細
```
URL: https://moneyforward.com/cf
```
- 当月収入・支出・収支
- 各取引の日付、内容、金額、金融機関、カテゴリ
- 前月に移動: `page.locator('a:has-text("◄"), button:has-text("◄")').first.click()`

### 3. 収支内訳 — カテゴリ別支出
```
URL: https://moneyforward.com/cf/summary
```
- 大項目別の金額と割合
- 月移動は家計簿ページと同じ◄ボタン

### 4. 月次推移 — 6ヶ月分の収支トレンド
```
URL: https://moneyforward.com/cf/monthly
```
- カテゴリ別の月次金額一覧（テーブル形式で取得可能）

### 5. 取引のカテゴリID（更新用）
各取引行のHTMLフォームに含まれる:
```
input[name="user_asset_act[id]"] — 取引ID
input[name="user_asset_act[large_category_id]"] — 大カテゴリID
input[name="user_asset_act[middle_category_id]"] — 中カテゴリID
```

既知のカテゴリID:
| カテゴリ | large_id | middle_id |
|---------|----------|-----------|
| 食費>食料品 | 11 | 41 |
| 日用品>日用品 | 10 | 36 |
| 住宅>住宅 | 4 | 107 |
| 教養・教育>書籍 | 12 | 20 |
| 趣味・娯楽>趣味・娯楽 | 13 | 47 |
| 衣服・美容>衣服 | 14 | 51 |
| 健康・医療>フィットネス | 16 | 57 |
| 通信費>情報サービス | 6 | 23 |
| 未分類>未分類 | 0 | 0 |
| 収入>給与 | 1 | 1 |

## 報告形式

```
## 総資産: XX,XXX,XXX円

## 口座残高
| 金融機関 | 残高 |
|----------|------|

## 当月収支 (YYYY年M月)
| 収入 | 支出 | 収支 |
|------|------|------|

## カテゴリ別支出
| カテゴリ | 金額 | 割合 |
|----------|------|------|

## 直近の入出金
| 日付 | 内容 | 金額 | 分類 |
|------|------|------|------|
```

## 注意事項
- SMBC 70,000円 = PayPay→SBI貯金振替（支出ではない）
- 定額自動入金 70,000円 = PayPay→SBI振替（収入ではない）
- 家賃はジャックス 88,880円/月
- Amazon.co.jpの取引はマネフォで「教養・教育>書籍」に自動分類されるが、実際は食品・日用品・家電等が混在。`/amazon-check` で正確な分類を確認すること
- headlessではForbiddenになるので必ずheadfulで起動する
- セッション切れの場合はブラウザが開くので手動で再ログイン