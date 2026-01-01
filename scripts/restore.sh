#!/bin/bash
#
# バックアップリストアスクリプト
#
# backup.sh で作成したバックアップからデータを復元します。
#
# 使用方法:
#   bash scripts/restore.sh <バックアップディレクトリ>
#
# 例:
#   bash scripts/restore.sh /var/www/backups/20260101_030000
#

set -e  # エラーが発生したら即座に終了

# ======================
# 設定
# ======================
PROJECT_ROOT="/var/www/fastapi_xserver"
DB_FILE="${PROJECT_ROOT}/xstock.db"
UPLOADS_DIR="${PROJECT_ROOT}/uploads"

# ======================
# 引数チェック
# ======================
if [ $# -ne 1 ]; then
    echo "使用方法: $0 <バックアップディレクトリ>"
    echo "例: $0 /var/www/backups/20260101_030000"
    exit 1
fi

BACKUP_DIR="$1"

if [ ! -d "${BACKUP_DIR}" ]; then
    echo "エラー: バックアップディレクトリが存在しません: ${BACKUP_DIR}"
    exit 1
fi

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
log "バックアップリストア開始"
log "バックアップ元: ${BACKUP_DIR}"
log "=========================================="

# 確認プロンプト
echo ""
echo "警告: 以下のデータが上書きされます："
echo "  - データベース: ${DB_FILE}"
echo "  - アップロード画像: ${UPLOADS_DIR}"
echo ""
read -p "続行しますか？ (yes/no): " CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
    log "リストアがキャンセルされました"
    exit 0
fi

# 1. チェックサムで整合性を確認
log "バックアップファイルの整合性を確認中..."

if [ -f "${BACKUP_DIR}/xstock.db.sha256" ]; then
    cd "${BACKUP_DIR}"
    if sha256sum -c xstock.db.sha256 > /dev/null 2>&1; then
        log "✓ データベースファイルの整合性確認OK"
    else
        log "エラー: データベースファイルのチェックサムが一致しません"
        exit 1
    fi
    cd - > /dev/null
else
    log "警告: データベースのチェックサムファイルがありません"
fi

if [ -f "${BACKUP_DIR}/uploads.tar.gz.sha256" ]; then
    cd "${BACKUP_DIR}"
    if sha256sum -c uploads.tar.gz.sha256 > /dev/null 2>&1; then
        log "✓ アップロード画像ファイルの整合性確認OK"
    else
        log "エラー: アップロード画像ファイルのチェックサムが一致しません"
        exit 1
    fi
    cd - > /dev/null
else
    log "警告: アップロード画像のチェックサムファイルがありません"
fi

# 2. Dockerコンテナを停止（安全のため）
log "Dockerコンテナを停止中..."
cd "${PROJECT_ROOT}"
docker compose down

# 3. 現在のデータをバックアップ（念のため）
RESTORE_BACKUP_DIR="${PROJECT_ROOT}/backup_before_restore_$(date +%Y%m%d_%H%M%S)"
log "現在のデータをバックアップ中: ${RESTORE_BACKUP_DIR}"
mkdir -p "${RESTORE_BACKUP_DIR}"

if [ -f "${DB_FILE}" ]; then
    cp "${DB_FILE}" "${RESTORE_BACKUP_DIR}/xstock.db"
fi

if [ -d "${UPLOADS_DIR}" ]; then
    tar -czf "${RESTORE_BACKUP_DIR}/uploads.tar.gz" -C "${PROJECT_ROOT}" uploads
fi

log "リストア前のバックアップ完了: ${RESTORE_BACKUP_DIR}"

# 4. データベースをリストア
if [ -f "${BACKUP_DIR}/xstock.db" ]; then
    log "データベースをリストア中: ${DB_FILE}"
    cp "${BACKUP_DIR}/xstock.db" "${DB_FILE}"
    log "✓ データベースリストア完了"
else
    log "警告: バックアップにデータベースファイルがありません"
fi

# 5. アップロード画像をリストア
if [ -f "${BACKUP_DIR}/uploads.tar.gz" ]; then
    log "アップロード画像をリストア中: ${UPLOADS_DIR}"

    # 既存のuploadsディレクトリを削除
    if [ -d "${UPLOADS_DIR}" ]; then
        rm -rf "${UPLOADS_DIR}"
    fi

    # tar.gzを展開
    tar -xzf "${BACKUP_DIR}/uploads.tar.gz" -C "${PROJECT_ROOT}"
    log "✓ アップロード画像リストア完了"
else
    log "警告: バックアップにアップロード画像がありません"
fi

# 6. 権限の修正
log "ファイル権限を修正中..."
chown -R yukayohei:yukayohei "${PROJECT_ROOT}"
chmod 644 "${DB_FILE}" 2>/dev/null || true
chmod -R 755 "${UPLOADS_DIR}" 2>/dev/null || true

# 7. Dockerコンテナを起動
log "Dockerコンテナを起動中..."
docker compose up -d --build

# 起動確認
sleep 3
log "コンテナ起動状態:"
docker ps | grep -E "fastapi-app|nginx-proxy" || log "警告: コンテナが起動していません"

log "=========================================="
log "バックアップリストア完了"
log "リストア元: ${BACKUP_DIR}"
log "リストア前のデータは保存されています: ${RESTORE_BACKUP_DIR}"
log "=========================================="

echo ""
echo "ログを確認してください:"
echo "  docker logs -f fastapi-app"
echo ""

exit 0
