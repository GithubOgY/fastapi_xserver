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
