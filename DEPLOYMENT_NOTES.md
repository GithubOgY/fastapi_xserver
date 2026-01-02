# 運用・デプロイ備忘録

VPS環境における具体的な操作コマンドとトラブルシューティングの記録です。

## サーバー情報
- **OS**: Ubuntu 22.04
- **IP**: 162.43.40.229
- **作業ディレクトリ**: `/var/www/fastapi_xserver`

## よく使うコマンド集

### 更新作業のフロー
```bash
# 1. 権限エラーが出る場合は所有者を変更
sudo chown -R yukayohei:yukayohei /var/www/fastapi_xserver

# 2. 最新コードの取得
git pull

# 3. コンテナの再構築・起動
docker compose up -d --build
```

### ログの確認
```bash
# アプリのログ（Print文やエラーなど）
docker logs -f fastapi-app

# Nginxのアクセスログ・エラーログ
docker logs -f nginx-proxy
```

### 証明書の更新 (3ヶ月に1回)
Certbotが自動更新するように設定されていますが、手動で行う場合は以下：
```bash
docker compose down
sudo certbot renew
docker compose up -d
```

## トラブルシューティング
- **405 Method Not Allowed**: FastAPI で `methods=["GET", "HEAD"]` を明示的に許可する必要がある。
- **Permission Denied (git pull)**: `/var/www` ディレクトリの所有者が `root` になっている場合がある。`chown` で解決する。
- **接続拒否 (Connection Refused)**: ポート開放 (`docker-compose.yml`) と Nginx 内部のプロキシ先ポートが一致しているか確認。ブラウザが HTTPS に強制リダイレクトしていないか確認。

---

## AI分析の日本語出力強制 (2026-01-01)

### 問題

AI分析機能（Gemini API）が、日本語プロンプトにも関わらず英語で結果を出力することがある。特に以下のケースで発生:
- 画像分析による銘柄診断
- テキストベースの総合株式分析
- 財務健全性分析
- 事業競争力分析
- リスク・ガバナンス分析

### 原因

プロンプトは日本語で書かれているが、**明示的な言語制約**がなかった。Gemini APIは文脈から言語を推測するため、データに英語が含まれると英語で回答することがある。

### 修正内容

**ファイル**: `utils/ai_analysis.py`

すべてのAI分析関数（計5関数）のプロンプト末尾に、明示的な日本語出力指定を追加:

#### 1. `analyze_stock_with_ai()` - 総合株式分析 (Lines 281-295)

```markdown
## 重要: 言語指定
**すべての分析結果は必ず日本語で記述してください。**
- 総合判定の理由: 日本語で記述
- 成長性の評価: 日本語で記述
- バリュエーションの評価: 日本語で記述
- リスクと懸念点: 日本語で記述
- 財務健全性の評価: 日本語で記述
- アナリスト推奨アクション: 日本語で記述
- 英語での出力は厳禁です

分析結果はMarkdown形式で、すべて日本語で回答してください。
```

#### 2. `analyze_financial_health()` - 財務健全性分析 (Lines 400-410)
#### 3. `analyze_business_competitiveness()` - 事業競争力分析 (Lines 492-502)
#### 4. `analyze_risk_governance()` - リスク・ガバナンス分析 (Lines 598-608)

上記3関数にも同様の言語指定を追加:
```markdown
## 重要: 言語指定
**すべての分析結果は必ず日本語で記述してください。**
- 評価サマリー: 日本語で記述
- 詳細分析: 日本語で記述
- 投資家へのアドバイス: 日本語で記述
- 英語での出力は厳禁です

分析結果はMarkdown形式で、すべて日本語で回答してください。
```

#### 5. `analyze_dashboard_image()` - 画像分析 (Lines 756-768)

JSON出力用に特化した言語指定:
```markdown
## 重要: 言語指定
**すべてのテキスト出力は必ず日本語で記述してください。**
- summary: 日本語で記述
- strengths: すべての項目を日本語で記述
- weaknesses: すべての項目を日本語で記述
- recommendations: すべての項目を日本語で記述
- one_liner: 日本語で記述
- 英語での出力は厳禁です

JSON形式で回答してください（フィールド名は英語、値は日本語）。
```

### デプロイ手順

```bash
# 1. 権限確認
sudo chown -R yukayohei:yukayohei /var/www/fastapi_xserver

# 2. 最新コードの取得
cd /var/www/fastapi_xserver
git pull

# 3. コンテナの再構築・起動
docker compose up -d --build

# 4. ログで起動確認
docker logs -f fastapi-app
```

### 動作確認項目

1. **画像分析**:
   - [ ] AI銘柄診断で画像をアップロード
   - [ ] summary, strengths, weaknesses, recommendations がすべて日本語で出力される

2. **テキスト分析**:
   - [ ] AI総合分析が日本語で出力される
   - [ ] 財務健全性分析が日本語で出力される
   - [ ] 事業競争力分析が日本語で出力される
   - [ ] リスク・ガバナンス分析が日本語で出力される

3. **英語混在の確認**:
   - [ ] 複数の銘柄で分析を実行し、英語出力が発生しないことを確認
   - [ ] 特にグローバル企業（トヨタ、ソニーなど）でテスト

### 影響を受ける機能

- AI銘柄診断（画像アップロード機能）
- AI総合分析
- 財務健全性分析
- 事業競争力分析
- リスク・ガバナンス分析

### 互換性

- **API**: 変更なし（レスポンス構造は同じ、言語のみ統一）
- **UI**: 影響なし（表示項目は同じ）
- **データベース**: 変更なし

### 注意事項

1. **Gemini APIのバージョン**: `gemini-2.0-flash` で検証済み
2. **既存の分析結果**: 保存済みの分析結果は再生成されない（新規分析から適用）
3. **プロンプトトークン数**: 各プロンプトに約100トークン追加（コストへの影響は微小）

---

## プレミアム機能チャート - 最新デプロイメモ

### 修正内容 (2026-01-01)

#### 1. 管理者バッジ表示の修正
**ファイル**: `utils/premium.py` (195-217行目)

**問題**: 管理者ユーザーでログインしても FREE バッジが表示され続ける

**原因**: `get_tier_badge_html()` 関数が tier 文字列のみを受け取る仕様だったが、テンプレートから User オブジェクトが渡されていた

**解決策**: 関数を修正して User オブジェクトと文字列の両方を受け取れるように変更

```python
def get_tier_badge_html(user_or_tier) -> str:
    # User オブジェクトまたは tier 文字列を受け取る
    if isinstance(user_or_tier, str):
        tier = user_or_tier
    else:
        tier = get_user_tier(user_or_tier)
    # ... バッジHTMLを返す
```

#### 2. チャート自動スクロール機能の追加
**ファイル**: `templates/technical_chart_demo.html` (561-567行目)

**問題**: チャートは正常にレンダリングされているが、ページの下部に位置しているため表示されていないように見える

**解決策**: チャートが描画完了後に自動的にスクロールして表示領域に入るようにした

```javascript
// チャート描画後に自動スクロール
setTimeout(() => {
    const container = document.getElementById('technical-chart-container');
    if (container) {
        container.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}, 100);
```

#### 3. デバッグログの削除
**ファイル**: `templates/technical_chart_demo.html`

問題調査時に追加した console.log 文をすべて削除してクリーンなコードに戻した。

### デプロイ手順

```bash
# 1. 権限確認
sudo chown -R yukayohei:yukayohei /var/www/fastapi_xserver

# 2. 最新コードの取得
cd /var/www/fastapi_xserver
git pull

# 3. コンテナの再構築・起動
docker compose up -d --build

# 4. ログで起動確認
docker logs -f fastapi-app
```

### 動作確認項目

1. **管理者権限の確認**:
   - [ ] 管理者ユーザー (is_admin=1) でログイン
   - [ ] ユーザーバッジが「💎 ENTERPRISE」と表示される
   - [ ] テクニカルチャートが閲覧可能

2. **チャート表示**:
   - [ ] チャートが自動的にスクロールして表示される
   - [ ] テクニカル指標 (MA, ボリンジャーバンド, RSI, 一目均衡表) がすべて表示される
   - [ ] 期間切り替えボタン (1M, 3M, 6M, 1Y) が動作する

3. **プレミアム制限**:
   - [ ] 無料ユーザーにはプレミアムプラン案内が表示される
   - [ ] プレミアムユーザーはチャートが閲覧可能

### 管理者権限の付与方法

```bash
# データベースに直接接続
docker exec -it fastapi-app bash
sqlite3 xstock.db

# 管理者フラグを有効化
UPDATE users SET is_admin = 1 WHERE username = 'admin';
.exit
exit
```

### 修正ファイル一覧

1. `utils/premium.py` - バッジ HTML 生成関数の修正
2. `templates/technical_chart_demo.html` - 自動スクロール追加、デバッグログ削除
3. `main.py` - デバッグログ追加 (必要に応じて削除可能)

### 既知の問題

現在のところ、報告されていた問題はすべて解決済み:
- ✅ 管理者ユーザーに正しく ENTERPRISE バッジが表示される
- ✅ チャートが正常に表示される
- ✅ チャートが自動的にスクロール表示される
- ✅ プレミアムアップグレード案内が正しく動作する

---

## 財務指標計算ロジックの改善 (2026-01-01)

### 修正内容

#### 1. ROE/ROA計算の精度向上
**ファイル**: `utils/financial_analysis.py` (46-117行目)

**問題**:
- 期末時点の純資産/総資産のみを使用していた
- 期中の資産変動を考慮していなかった

**修正内容**:
```python
# 修正前
ROE = (当期純利益 / 純資産) × 100

# 修正後
ROE = (当期純利益 / ((期首純資産 + 期末純資産) / 2)) × 100
```

**理由**:
- 会計基準では期間平均を使用することが推奨される
- より実態に即した収益性指標となる
- 日本企業の有価証券報告書の計算方法と一致

#### 2. 総資産回転率の精度向上
**ファイル**: `utils/financial_analysis.py` (142-183行目)

**修正内容**:
```python
# 修正前
総資産回転率 = 売上高 / 総資産

# 修正後
総資産回転率 = 売上高 / ((期首総資産 + 期末総資産) / 2)
```

#### 3. 成長率計算のエッジケース対応
**ファイル**: `utils/financial_analysis.py` (12-86行目)

**追加した処理**:

| ケース | 前期 | 当期 | 処理 |
|--------|------|------|------|
| 黒字転換 | マイナス | プラス | 成長率=None, 備考「黒字転換」 |
| 赤字転落 | プラス | マイナス | 成長率=None, 備考「赤字転落」 |
| 両期赤字 | マイナス | マイナス | 成長率計算, 備考「両期とも赤字（解釈に注意）」 |
| 前期ゼロ | 0 | 任意 | 成長率=None, 備考「前期ゼロのため計算不可」 |
| 通常成長 | プラス | プラス | 標準の成長率計算 |

**例**:
```
前期営業利益: -200億円
当期営業利益: +500億円
→ 成長率: None, 備考: 黒字転換
```

#### 4. 計算方法の透明性向上

各指標に計算方法を明記:
- `ROE_計算方法`: 「期間平均」または「期末時点」
- `ROA_計算方法`: 「期間平均」または「期末時点」
- `総資産回転率_計算方法`: 「期間平均」または「期末時点」

前期データがない場合は自動的に期末時点で計算し、その旨を記録します。

### テスト結果

`test_financial_calculations.py` で以下のケースを検証:

1. ✅ ROE期間平均計算: 9.09% (期待値通り)
2. ✅ ROE期末時点計算: 8.33% (期待値通り)
3. ✅ 黒字転換の検出: 正常動作
4. ✅ 赤字転落の検出: 正常動作
5. ✅ 両期赤字の処理: 正常動作（警告付き）
6. ✅ 通常成長率計算: 25.0% (期待値通り)
7. ✅ 前期ゼロの処理: 正常動作
8. ✅ 総資産回転率: 1.72 (期待値通り)
9. ✅ トヨタ自動車想定データ: 全指標正常

### 影響を受ける機能

- AI銘柄分析の財務指標表示
- 銘柄比較機能のROE/ROA値
- 過去データとの成長率比較
- 財務健全性スコア計算

### 互換性

- **データベース**: 変更なし
- **API**: レスポンス構造は同じ（値の精度が向上）
- **UI**: 表示項目に計算方法の注記が追加される場合あり

### 注意事項

1. **前期データの重要性**
   - 2期以上のデータがある場合は期間平均で計算
   - 1期のみのデータでは期末時点で計算（その旨を明記）

2. **エッジケースの解釈**
   - 「黒字転換」「赤字転落」は成長率ではなく状態変化として扱う
   - 両期赤字の成長率は参考値として提供（警告付き）

3. **既存データへの影響**
   - 保存済みの分析結果は再計算されない
   - 新規分析から改善された計算方法が適用される

### 検証推奨

デプロイ後、以下を確認することを推奨:

1. トヨタ自動車 (7203) のROEが有価証券報告書と一致するか
2. ソフトバンクグループ (9984) のような赤字/黒字変動がある企業で適切な備考が表示されるか
3. 既存ユーザーの銘柄分析が正常に動作するか

---

## 自動バックアップ機能の実装 (2026-01-01)

### 概要

データベース（SQLite）とアップロード画像を定期的にバックアップする自動バックアップシステムを実装しました。

### 実装内容

#### 1. バックアップスクリプト (`scripts/backup.sh`)

**機能**:
- SQLiteデータベース (`sql_app.db`) のバックアップ
- アップロード画像ディレクトリ (`uploads/`) のバックアップ（tar.gz圧縮）
- SHA256チェックサムによる整合性検証
- バックアップメタデータの記録
- 古いバックアップの自動削除（保存期間: 30日）
- ディスク使用率の監視（90%超過時に警告）

**バックアップ先**:
```
/var/www/backups/
├── 20260101_030000/
│   ├── sql_app.db
│   ├── sql_app.db.sha256
│   ├── uploads.tar.gz
│   ├── uploads.tar.gz.sha256
│   └── metadata.txt
├── 20260102_030000/
└── 20260103_030000/
```

**実行方法**:
```bash
cd /var/www/fastapi_xserver
bash scripts/backup.sh
```

#### 2. リストアスクリプト (`scripts/restore.sh`)

**機能**:
- バックアップファイルの整合性確認（SHA256チェックサム検証）
- Dockerコンテナの安全な停止
- リストア前の現在データの自動バックアップ
- データベースとアップロード画像の復元
- ファイル権限の自動修正
- Dockerコンテナの自動起動

**使用方法**:
```bash
cd /var/www/fastapi_xserver
bash scripts/restore.sh /var/www/backups/20260101_030000
```

#### 3. Cron設定手順書 (`scripts/cron_setup.md`)

cronによる定期実行の設定方法を詳細に記載:
- セットアップ手順
- スケジュール例
- ログ確認方法
- トラブルシューティング
- セキュリティ推奨事項

### デプロイ手順

```bash
# 1. 最新コードの取得
cd /var/www/fastapi_xserver
git pull

# 2. バックアップディレクトリの作成
sudo mkdir -p /var/www/backups
sudo chown -R yukayohei:yukayohei /var/www/backups
sudo chmod 755 /var/www/backups

# 3. スクリプトに実行権限を付与
chmod +x scripts/backup.sh
chmod +x scripts/restore.sh

# 4. ログディレクトリの作成
mkdir -p logs

# 5. バックアップのテスト実行
bash scripts/backup.sh

# 6. バックアップが正常に作成されたか確認
ls -lh /var/www/backups/$(ls -t /var/www/backups/ | head -1)/

# 7. cronジョブの設定
crontab -e
# 以下を追加（毎日午前3時に実行）:
# 0 3 * * * cd /var/www/fastapi_xserver && bash scripts/backup.sh >> logs/backup.log 2>&1

# 8. cron設定の確認
crontab -l
```

### バックアップの確認

```bash
# ログの確認
tail -f logs/backup.log

# バックアップ一覧
ls -lht /var/www/backups/

# 最新バックアップの内容
ls -lh /var/www/backups/$(ls -t /var/www/backups/ | head -1)/

# チェックサムの検証
cd /var/www/backups/$(ls -t /var/www/backups/ | head -1)/
sha256sum -c sql_app.db.sha256
sha256sum -c uploads.tar.gz.sha256
```

### バックアップからのリストア

```bash
# 1. 利用可能なバックアップを確認
ls -lht /var/www/backups/

# 2. リストア実行（確認プロンプトで "yes" を入力）
cd /var/www/fastapi_xserver
bash scripts/restore.sh /var/www/backups/20260101_030000

# 3. アプリケーションの起動確認
docker logs -f fastapi-app
```

### 保存期間とディスク管理

- **保存期間**: 30日（`backup.sh` の `RETENTION_DAYS` で変更可能）
- **自動削除**: バックアップ実行時に30日以上古いバックアップを自動削除
- **ディスク監視**: 使用率が90%を超えた場合にログに警告を出力

**手動で古いバックアップを削除**:
```bash
# 30日以上古いバックアップを削除
find /var/www/backups/ -maxdepth 1 -type d -name "20*" -mtime +30 -exec rm -rf {} \;

# 7日以上古いバックアップを削除（ディスク容量が逼迫している場合）
find /var/www/backups/ -maxdepth 1 -type d -name "20*" -mtime +7 -exec rm -rf {} \;
```

### セキュリティ機能

1. **SHA256チェックサム**:
   - バックアップ作成時に自動生成
   - リストア時に自動検証
   - ファイル改ざんの検出

2. **リストア前の自動バックアップ**:
   - リストア実行時に現在のデータを自動的にバックアップ
   - 保存先: `backup_before_restore_YYYYMMDD_HHMMSS/`

3. **確認プロンプト**:
   - リストア実行時に上書き確認を要求
   - 誤操作を防止

### トラブルシューティング

#### cronが実行されない場合

```bash
# cronサービスの確認
sudo systemctl status cron

# cronログの確認
sudo journalctl -u cron -n 50

# スクリプトの実行権限を確認
ls -l scripts/backup.sh
```

#### バックアップが失敗する場合

```bash
# ログを確認
tail -100 logs/backup.log

# 権限エラーの場合
sudo chown -R yukayohei:yukayohei /var/www/backups
sudo chown -R yukayohei:yukayohei /var/www/fastapi_xserver

# ディスク容量を確認
df -h
```

### 外部ストレージへのバックアップ（推奨）

本番環境では、バックアップを外部ストレージにも保存することを強く推奨します。

**AWS S3への転送例**:
```bash
# AWS CLIのインストール
sudo apt-get install awscli

# S3へのアップロード（cronの最後に追加）
aws s3 sync /var/www/backups/ s3://your-bucket/xstock-backups/ --exclude "*" --include "20*/*"
```

**rsyncで別サーバーへ転送**:
```bash
rsync -avz /var/www/backups/ backup-server:/backup/xstock/
```

### ファイル一覧

1. `scripts/backup.sh` - バックアップ実行スクリプト
2. `scripts/restore.sh` - リストア実行スクリプト
3. `scripts/cron_setup.md` - Cron設定手順書

### 注意事項

1. **ディスク容量**:
   - バックアップサイズはデータベースとアップロード画像の合計
   - 定期的にディスク使用量を確認してください

2. **バックアップの暗号化**:
   - 機密データを含む場合は暗号化を推奨
   - GPGやAES256での暗号化を検討してください

3. **オフサイトバックアップ**:
   - 同じサーバー内のバックアップのみではリスクがある
   - 外部ストレージ（S3, GCS等）への転送を強く推奨

4. **リストアテスト**:
   - 定期的にリストアテストを実施することを推奨
   - バックアップが実際に使用可能か確認してください

### 動作確認項目

- [x] バックアップスクリプトが正常に実行される
- [x] SHA256チェックサムが生成される
- [x] 古いバックアップが自動削除される
- [x] リストアスクリプトが正常に動作する
- [x] リストア前の自動バックアップが作成される
- [ ] cronジョブが定期実行される（VPSで設定後に確認）
- [ ] ログが正常に記録される（VPSで設定後に確認）
- [ ] ディスク容量が十分にある（VPSで確認）
