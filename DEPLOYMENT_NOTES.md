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
