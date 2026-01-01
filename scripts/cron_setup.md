# Cron設定手順書 - 自動バックアップ

このドキュメントでは、自動バックアップをcronで定期実行する設定方法を説明します。

## 📋 前提条件

- VPSサーバーにSSHでログイン済み
- バックアップスクリプトがデプロイ済み (`/var/www/fastapi_xserver/scripts/backup.sh`)
- バックアップ保存先ディレクトリが存在する (`/var/www/backups`)

## 🚀 セットアップ手順

### 1. バックアップディレクトリの作成

```bash
# バックアップ保存先を作成
sudo mkdir -p /var/www/backups

# 権限を設定（yukayoheiユーザーが書き込めるようにする）
sudo chown -R yukayohei:yukayohei /var/www/backups
sudo chmod 755 /var/www/backups
```

### 2. スクリプトに実行権限を付与

```bash
cd /var/www/fastapi_xserver

# バックアップスクリプトに実行権限を付与
chmod +x scripts/backup.sh
chmod +x scripts/restore.sh
```

### 3. 手動でバックアップをテスト実行

```bash
# バックアップスクリプトをテスト実行
bash scripts/backup.sh

# バックアップが正常に作成されたか確認
ls -lh /var/www/backups/

# 最新のバックアップディレクトリの内容を確認
ls -lh /var/www/backups/$(ls -t /var/www/backups/ | head -1)/
```

**期待される出力**:
```
xstock.db
xstock.db.sha256
uploads.tar.gz
uploads.tar.gz.sha256
metadata.txt
```

### 4. ログディレクトリの作成

```bash
mkdir -p /var/www/fastapi_xserver/logs
```

### 5. cronジョブの設定

```bash
# crontabを編集
crontab -e
```

以下の行を追加します：

```cron
# 毎日午前3時にバックアップを実行（日本時間の場合はUTC-9なので18時）
0 3 * * * cd /var/www/fastapi_xserver && bash scripts/backup.sh >> logs/backup.log 2>&1

# または、サーバーがUTCの場合（日本時間午前3時 = UTC午後6時前日）
0 18 * * * cd /var/www/fastapi_xserver && bash scripts/backup.sh >> logs/backup.log 2>&1
```

**cron時刻の説明**:
```
分 時 日 月 曜日
│ │ │ │ │
│ │ │ │ └─ 曜日 (0-7, 0と7は日曜日)
│ │ │ └─── 月 (1-12)
│ │ └───── 日 (1-31)
│ └─────── 時 (0-23)
└───────── 分 (0-59)
```

**その他のスケジュール例**:
```cron
# 毎週日曜日の午前3時
0 3 * * 0 cd /var/www/fastapi_xserver && bash scripts/backup.sh >> logs/backup.log 2>&1

# 毎月1日の午前3時
0 3 1 * * cd /var/www/fastapi_xserver && bash scripts/backup.sh >> logs/backup.log 2>&1

# 12時間ごと（午前3時と午後3時）
0 3,15 * * * cd /var/www/fastapi_xserver && bash scripts/backup.sh >> logs/backup.log 2>&1
```

### 6. cron設定の確認

```bash
# 設定されたcronジョブを確認
crontab -l
```

### 7. cronサービスの起動確認

```bash
# cronサービスが起動しているか確認
sudo systemctl status cron

# 起動していない場合は起動
sudo systemctl start cron

# 自動起動を有効化
sudo systemctl enable cron
```

## 🔍 バックアップの確認

### ログの確認

```bash
# バックアップログをリアルタイムで監視
tail -f /var/www/fastapi_xserver/logs/backup.log

# 最新のバックアップログを表示
tail -50 /var/www/fastapi_xserver/logs/backup.log
```

### バックアップファイルの確認

```bash
# すべてのバックアップをリスト表示
ls -lht /var/www/backups/

# 最新のバックアップの中身を確認
ls -lh /var/www/backups/$(ls -t /var/www/backups/ | head -1)/

# バックアップのメタデータを表示
cat /var/www/backups/$(ls -t /var/www/backups/ | head -1)/metadata.txt
```

### バックアップの整合性確認

```bash
# 最新バックアップのチェックサムを検証
cd /var/www/backups/$(ls -t /var/www/backups/ | head -1)/
sha256sum -c xstock.db.sha256
sha256sum -c uploads.tar.gz.sha256
```

## 🔄 バックアップからのリストア

### リストア手順

```bash
# 1. 利用可能なバックアップを確認
ls -lht /var/www/backups/

# 2. リストアしたいバックアップを選択（例: 20260101_030000）
BACKUP_DIR=/var/www/backups/20260101_030000

# 3. リストアスクリプトを実行
cd /var/www/fastapi_xserver
bash scripts/restore.sh ${BACKUP_DIR}

# 4. アプリケーションが正常に起動したか確認
docker logs -f fastapi-app
```

**注意**: リストア時には確認プロンプトが表示されます。`yes` と入力して続行してください。

## 📊 ディスク容量の監視

### 現在のディスク使用量を確認

```bash
# バックアップディレクトリの容量
du -sh /var/www/backups/

# ディスク全体の使用状況
df -h
```

### 古いバックアップの手動削除

```bash
# 30日以上古いバックアップを削除（backup.shで自動実行されますが、手動も可能）
find /var/www/backups/ -maxdepth 1 -type d -name "20*" -mtime +30 -exec rm -rf {} \;
```

## ⚠️ トラブルシューティング

### cronが実行されない場合

1. **cronサービスの確認**:
   ```bash
   sudo systemctl status cron
   sudo journalctl -u cron -n 50
   ```

2. **スクリプトの実行権限を確認**:
   ```bash
   ls -l /var/www/fastapi_xserver/scripts/backup.sh
   ```

3. **スクリプトのパスを絶対パスに変更**:
   ```cron
   0 3 * * * /usr/bin/bash /var/www/fastapi_xserver/scripts/backup.sh >> /var/www/fastapi_xserver/logs/backup.log 2>&1
   ```

### バックアップが失敗する場合

1. **ログを確認**:
   ```bash
   tail -100 /var/www/fastapi_xserver/logs/backup.log
   ```

2. **権限エラーの場合**:
   ```bash
   sudo chown -R yukayohei:yukayohei /var/www/backups
   sudo chown -R yukayohei:yukayohei /var/www/fastapi_xserver
   ```

3. **ディスク容量不足の場合**:
   ```bash
   df -h
   # 古いバックアップを削除
   find /var/www/backups/ -maxdepth 1 -type d -name "20*" -mtime +7 -exec rm -rf {} \;
   ```

## 📧 バックアップ失敗時の通知（オプション）

バックアップ失敗時にメール通知を受け取りたい場合は、`backup.sh` の最後に以下を追加：

```bash
# バックアップ失敗時にメール送信
if [ $? -ne 0 ]; then
    echo "バックアップが失敗しました" | mail -s "Backup Failed" your-email@example.com
fi
```

## 🔐 セキュリティ推奨事項

1. **バックアップディレクトリの権限を制限**:
   ```bash
   chmod 700 /var/www/backups
   ```

2. **外部ストレージへのバックアップ**（推奨）:
   - AWS S3
   - Google Cloud Storage
   - rsyncで別サーバーへ転送

   例: S3へのアップロード
   ```bash
   aws s3 sync /var/www/backups/ s3://your-bucket/xstock-backups/
   ```

3. **バックアップの暗号化**（機密データの場合）:
   ```bash
   # GPGで暗号化
   gpg --symmetric --cipher-algo AES256 xstock.db
   ```

## ✅ チェックリスト

セットアップ完了後、以下を確認してください：

- [ ] `/var/www/backups` ディレクトリが存在し、権限が正しい
- [ ] スクリプトに実行権限が付与されている
- [ ] 手動実行でバックアップが成功する
- [ ] cronジョブが登録されている (`crontab -l` で確認)
- [ ] cronサービスが起動している
- [ ] ログファイルが正常に記録される
- [ ] リストアスクリプトが正常に動作する
- [ ] ディスク容量が十分にある

---

これで自動バックアップの設定は完了です！
