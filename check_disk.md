# ディスク容量確認と対処方法

## 1. ディスク使用状況の確認
```bash
df -h
```

## 2. 容量を使っているディレクトリの特定
```bash
du -sh /var/www/* | sort -h
du -sh /var/www/backups/* | sort -h
du -sh /var/www/fastapi_xserver/* | sort -h
```

## 3. Docker関連のクリーンアップ（推奨）
```bash
# 停止中のコンテナを削除
docker container prune -f

# 未使用のイメージを削除
docker image prune -a -f

# 未使用のボリュームを削除
docker volume prune -f

# ビルドキャッシュを削除
docker builder prune -a -f
```

## 4. 古いバックアップの削除（必要に応じて）
```bash
# 7日以上前のバックアップを削除
find /var/www/backups -type d -name "20*" -mtime +7 -exec rm -rf {} \;
```

## 5. ログファイルのクリーンアップ
```bash
# Dockerログの確認
docker system df

# 古いログの削除（慎重に）
journalctl --vacuum-time=3d
```

## 6. 再度デプロイ
```bash
cd /var/www/fastapi_xserver
git fetch origin
git reset --hard origin/main
docker compose up -d --build
```
