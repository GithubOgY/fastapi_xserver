#!/bin/bash
#
# 自動バックアップスクリプト
#
# データベース（SQLite）とアップロード画像を定期的にバックアップします。
# cronで実行することを想定しています。
#
# 使用方法:
#   bash scripts/backup.sh
#
# cronの設定例（毎日午前3時に実行）:
#   0 3 * * * cd /var/www/fastapi_xserver && bash scripts/backup.sh >> logs/backup.log 2>&1
#

set -e  # エラーが発生したら即座に終了

# ======================
# 設定
# ======================
PROJECT_ROOT="/var/www/fastapi_xserver"
BACKUP_ROOT="/var/www/backups"
DB_FILE="${PROJECT_ROOT}/xstock.db"
UPLOADS_DIR="${PROJECT_ROOT}/uploads"

# バックアップ保存先（日付ごと）
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

# 保存期間（日数）- これより古いバックアップは自動削除
RETENTION_DAYS=30

# ======================
# 関数定義
# ======================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1"
}

# ======================
# メイン処理
# ======================

log "=========================================="
log "バックアップ開始: ${TIMESTAMP}"
log "=========================================="

# バックアップディレクトリの作成
log "バックアップディレクトリを作成: ${BACKUP_DIR}"
mkdir -p "${BACKUP_DIR}"

# 1. データベースのバックアップ
if [ -f "${DB_FILE}" ]; then
    log "データベースをバックアップ中: ${DB_FILE}"
    cp "${DB_FILE}" "${BACKUP_DIR}/xstock.db"

    # SHA256チェックサムを生成（整合性確認用）
    sha256sum "${BACKUP_DIR}/xstock.db" > "${BACKUP_DIR}/xstock.db.sha256"

    log "データベースバックアップ完了"
else
    log "警告: データベースファイルが見つかりません: ${DB_FILE}"
fi

# 2. アップロード画像のバックアップ
if [ -d "${UPLOADS_DIR}" ]; then
    log "アップロード画像をバックアップ中: ${UPLOADS_DIR}"

    # uploadsディレクトリをtar.gzで圧縮
    tar -czf "${BACKUP_DIR}/uploads.tar.gz" -C "${PROJECT_ROOT}" uploads

    # SHA256チェックサムを生成
    sha256sum "${BACKUP_DIR}/uploads.tar.gz" > "${BACKUP_DIR}/uploads.tar.gz.sha256"

    log "アップロード画像バックアップ完了"
else
    log "警告: アップロードディレクトリが見つかりません: ${UPLOADS_DIR}"
fi

# 3. バックアップメタデータの記録
cat > "${BACKUP_DIR}/metadata.txt" <<EOF
バックアップ日時: ${TIMESTAMP}
プロジェクトルート: ${PROJECT_ROOT}
データベースファイル: ${DB_FILE}
アップロードディレクトリ: ${UPLOADS_DIR}

バックアップ内容:
- xstock.db (データベース)
- xstock.db.sha256 (データベースのチェックサム)
- uploads.tar.gz (アップロード画像の圧縮ファイル)
- uploads.tar.gz.sha256 (画像圧縮ファイルのチェックサム)
- metadata.txt (このファイル)

リストア方法:
  1. データベースをリストア:
     cp xstock.db ${DB_FILE}

  2. アップロード画像をリストア:
     tar -xzf uploads.tar.gz -C ${PROJECT_ROOT}

  3. チェックサムで整合性を確認:
     sha256sum -c xstock.db.sha256
     sha256sum -c uploads.tar.gz.sha256
EOF

log "バックアップメタデータを記録"

# 4. バックアップサイズの確認
BACKUP_SIZE=$(du -sh "${BACKUP_DIR}" | awk '{print $1}')
log "バックアップサイズ: ${BACKUP_SIZE}"

# 5. 古いバックアップの自動削除
log "古いバックアップを削除中（保存期間: ${RETENTION_DAYS}日）"

find "${BACKUP_ROOT}" -maxdepth 1 -type d -name "20*" -mtime +${RETENTION_DAYS} -exec rm -rf {} \; 2>/dev/null || true

REMAINING_BACKUPS=$(find "${BACKUP_ROOT}" -maxdepth 1 -type d -name "20*" | wc -l)
log "残存バックアップ数: ${REMAINING_BACKUPS}"

# 6. ディスク使用量の確認
DISK_USAGE=$(df -h "${BACKUP_ROOT}" | tail -1 | awk '{print $5}')
log "バックアップディスクの使用率: ${DISK_USAGE}"

# 警告: ディスク使用率が90%を超えた場合
if [ "${DISK_USAGE%\%}" -gt 90 ]; then
    log "警告: バックアップディスクの使用率が90%を超えています！"
fi

log "=========================================="
log "バックアップ完了: ${TIMESTAMP}"
log "バックアップ先: ${BACKUP_DIR}"
log "=========================================="

exit 0
