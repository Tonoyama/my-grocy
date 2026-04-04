# Amazon注文分析

Amazon.co.jpの注文履歴を取得し、カテゴリ別に分類・分析する。マネーフォワードの誤分類も特定する。

## 前提
- Playwright (Python): `pip3 install playwright && python3 -m playwright install chromium`
- 永続Chromeプロファイル: `~/.mf_chrome_profile`（マネーフォワードと共有）
- 初回のみブラウザが開くので手動でAmazonにログイン

## 認証・接続

マネーフォワードと同じ永続プロファイルを使用:
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

## 手順

### 1. 注文履歴の取得
```
URL: https://www.amazon.co.jp/your-orders/orders?orderFilter=months-3
ページネーション: &startIndex={ページ番号*10}  (0, 10, 20, ...)
```

各ページから以下をテキスト抽出:
- 注文日（`注文日 YYYY年M月D日`）
- 合計金額（`合計 ￥XX,XXX`）
- 商品名（リンクテキスト）

### 2. カテゴリ自動分類

以下のキーワードマッチで分類:

| カテゴリ | キーワード |
|----------|-----------|
| 食品・調味料 | 醤油, みそ, 味噌, 料理酒, みりん, ラーメン, スープ, 小麦粉, ごま, トマト, フンドーキン, エバラ, マルタイ, デルモンテ, キッコーマン, ヒガシマル, 日の出, ネットスーパー, ニトリル手袋 |
| キッチン用品 | 鍋, テボ, 温度計, ジップロック, フリーザー, ボウル, 皿, 食洗機, 食器, コンテナー, 計量スプーン, 骨抜き, 水切りネット, レンジフード |
| 家電・電子機器 | Anker, Soundcore, MAONO, マイク, カードリーダー, USB, UGREEN |
| スマートホーム | SwitchBot, Echo Dot, Alexa |
| 日用品 | 洗濯, カビキラー, ペーパータオル, シャンプー, ディスペンサー, 浄水, 加湿器, 除菌, キュキュット |
| 家具・生活用品 | カーテン, ランチョンマット, 枕, バスマット, 珪藻土, ハンコ |
| 照明 | シーリングライト, スポットライト |
| 書籍(技術書) | Kindle, プログラミング, Python, Docker, AWS, Kubernetes, 入門, 実践, エンジニア, 設計 |
| 漫画 | FX戦士, コミック |
| 衣服・アウトドア | 登山, サングラス, ジャケット, 手袋, シューズ |
| 健康・運動 | ルームランナー, エアロバイク |

マッチしないものは「その他」に分類。

### 3. マネーフォワード誤分類の特定

マネフォはAmazon.co.jpの取引を全て「教養・教育>書籍」に自動分類する。
上記のカテゴリ分類結果と照合し、誤分類されている取引を一覧で報告する。

### 4. 報告形式

```
## Amazon注文分析（直近N件）

### カテゴリ別支出
| カテゴリ | 金額 | 割合 | 件数 |
|----------|------|------|------|

### 月別内訳
| カテゴリ | 1月 | 2月 | 3月 | 4月 |
|----------|-----|-----|-----|-----|

### マネフォ誤分類
| 金額 | 商品名 | MF分類 | 正しい分類 |
|------|--------|--------|-----------|
```

## 注意事項
- headfulで起動すること（headlessではAmazonがブロック）
- ページ数が多い場合（14ページ等）は全ページ取得に数分かかる
- 同一注文に複数商品が含まれる場合、金額は注文単位。商品単位の金額は取得できない
- 金額ベースでのカテゴリマッチは不正確な場合がある（同額の別商品）
- 返品（AMAZON.CO.JP (返品)）は収入として扱うこと