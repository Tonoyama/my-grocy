# 健康データ確認

Health Planet（体重・体脂肪率）とあすけん（栄養評価）のデータを取得して報告する。

## 前提
- Playwright (Python): `pip3 install playwright && python3 -m playwright install chromium`
- 認証情報: `.env` に以下を設定
  - `HP_CLIENT_ID`, `HP_CLIENT_SECRET`, `HP_USER`, `HP_PASSWORD` (Health Planet)
  - `ASKEN_EMAIL`, `ASKEN_PASSWORD` (あすけん)
- スクリプト:
  - `healthplanet-fetch.py` — Health Planet APIから体重・体脂肪率取得
  - `asken-fetch.py` — あすけんからデータ取得

## 手順

### 1. 体重・体脂肪率の取得
```bash
python3 /Users/ytonoyam/Dev/my-grocy/healthplanet-fetch.py --days 14
```
- OAuth2トークンは `.healthplanet_token.json` にキャッシュ（30日有効）
- 出力: 日時、体重(kg)、体脂肪率(%)
- JSONデータ: `/tmp/healthplanet_data.json`

### 2. あすけんの栄養評価取得

#### 特定日のアドバイス（全日）
Playwrightでログイン後:
```
URL: https://www.asken.jp/wsp/advice/YYYY-MM-DD
```
テキスト抽出で栄養素データを取得。

#### 特定日の食事記録確認
```
URL: https://www.asken.jp/wsp/comment/YYYY-MM-DD
```

#### 週間データ
```bash
python3 /Users/ytonoyam/Dev/my-grocy/asken-fetch.py --week
```

### 3. 報告形式

以下の形式で報告する:

```
## 体重推移（直近2週間）
| 日付 | 体重 | 体脂肪率 | 傾向 |
|------|------|---------|------|

## 栄養評価（昨日）
| 栄養素 | 摂取量 | 基準値 | 判定 |
|--------|--------|--------|------|

## 不足栄養素と推奨食材
- ...

## 今日の献立への提案
- ...
```

## Health Planet API 仕様
- OAuth認証: Playwrightでブラウザログイン→承認→コード取得→トークン交換
- ログインフォーム: `input[name="loginId"]`, `input[name="passwd"]`, `input[type="image"]`
- 承認ページ: `input[name="approval"]` を `true` に設定してフォームsubmit
- コード取得: 承認後のページの `textarea` からコード取得
- トークンAPI: `POST https://www.healthplanet.jp/oauth/token`
- 体組成API: `GET https://www.healthplanet.jp/status/innerscan.json`
  - tag: 6021(体重kg), 6022(体脂肪率%)
  - date: 1(測定日付), from/to: yyyyMMddHHmmss形式