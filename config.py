"""
アプリケーション設定ファイル
Application Configuration File

このファイルは、Xserver株式分析アプリケーションの初期設定を管理します。
環境変数、言語設定、データベース設定などを一元管理します。
"""

import os
from typing import Dict, List
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()


class AppConfig:
    """アプリケーション基本設定"""

    # アプリケーション情報
    APP_NAME: str = "Xserver株式分析"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "日本株式市場の財務分析・AI分析プラットフォーム"

    # 言語設定
    DEFAULT_LANGUAGE: str = "ja"  # 日本語がデフォルト
    SUPPORTED_LANGUAGES: List[str] = ["ja", "en"]

    # タイムゾーン設定
    TIMEZONE: str = "Asia/Tokyo"
    DATE_FORMAT: str = "%Y年%m月%d日"
    DATETIME_FORMAT: str = "%Y年%m月%d日 %H:%M:%S"

    # ページネーション設定
    ITEMS_PER_PAGE: int = 20
    MAX_ITEMS_PER_PAGE: int = 100


class SecurityConfig:
    """セキュリティ関連設定"""

    # JWT認証設定
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-placeholder")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # 管理者アカウント
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "password")

    # パスワードポリシー
    MIN_PASSWORD_LENGTH: int = 8
    REQUIRE_SPECIAL_CHAR: bool = True
    REQUIRE_NUMBER: bool = True


class DatabaseConfig:
    """データベース設定"""

    # データベース接続情報
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")
    DB_USER: str = os.getenv("DB_USER", "user")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "password")
    DB_NAME: str = os.getenv("DB_NAME", "stock_db")

    # コネクションプール設定
    POOL_SIZE: int = 5
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30
    POOL_RECYCLE: int = 3600


class EmailConfig:
    """メール送信設定"""

    # Gmail SMTP設定
    MAIL_USERNAME: str = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD: str = os.getenv("MAIL_PASSWORD", "")
    MAIL_FROM: str = os.getenv("MAIL_FROM", "")
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_PORT: int = 587
    MAIL_USE_TLS: bool = True

    # メールテンプレート設定
    MAIL_SUBJECT_PREFIX: str = "[Xserver株式分析] "


class ExternalAPIConfig:
    """外部API設定"""

    # EDINET API（金融庁の企業情報開示システム）
    EDINET_API_KEY: str = os.getenv("EDINET_API_KEY", "")
    EDINET_BASE_URL: str = "https://disclosure.edinet-fsa.go.jp/api/v2"

    # Gemini AI API（Google）
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # J-Quants API（日本取引所グループ）
    JQUANTS_API_KEY: str = os.getenv("JQUANTS_API_KEY", "")
    JQUANTS_BASE_URL: str = "https://api.jquants.com/v1"

    # Yahoo Finance（株価データ）
    YAHOO_FINANCE_ENABLED: bool = True


class LoggingConfig:
    """ログ設定"""

    # ログディレクトリ
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")

    # ログファイル設定
    LOG_FILE: str = f"{LOG_DIR}/app.log"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT: int = 5

    # ログレベル
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ログフォーマット
    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


class CacheConfig:
    """キャッシュ設定"""

    # AI分析結果のキャッシュ有効期限（秒）
    AI_ANALYSIS_CACHE_EXPIRY: int = 3600 * 24 * 7  # 7日間

    # 財務データのキャッシュ有効期限（秒）
    FINANCIAL_DATA_CACHE_EXPIRY: int = 3600 * 24  # 1日

    # 株価データのキャッシュ有効期限（秒）
    STOCK_PRICE_CACHE_EXPIRY: int = 3600  # 1時間


class UIConfig:
    """UI/UX設定"""

    # テーマ設定
    DEFAULT_THEME: str = "light"
    ENABLE_DARK_MODE: bool = True

    # 表示設定
    SHOW_BETA_FEATURES: bool = False
    ENABLE_ANIMATIONS: bool = True

    # チャート設定
    DEFAULT_CHART_TYPE: str = "candlestick"  # ローソク足チャート
    CHART_TIME_RANGES: List[str] = ["1D", "1W", "1M", "3M", "6M", "1Y", "5Y"]

    # 通貨表示
    CURRENCY_SYMBOL: str = "¥"
    CURRENCY_CODE: str = "JPY"

    # 数値フォーマット
    NUMBER_DECIMAL_PLACES: int = 2
    LARGE_NUMBER_FORMAT: str = "万円"  # 万円単位で表示


class FeatureFlags:
    """機能フラグ設定"""

    # 機能の有効/無効
    ENABLE_AI_ANALYSIS: bool = True
    ENABLE_EMAIL_NOTIFICATIONS: bool = True
    ENABLE_USER_COMMENTS: bool = True
    ENABLE_SOCIAL_FEATURES: bool = True
    ENABLE_PWA: bool = True
    ENABLE_OFFLINE_MODE: bool = True

    # ベータ機能
    ENABLE_PORTFOLIO_TRACKING: bool = False
    ENABLE_REAL_TIME_ALERTS: bool = False
    ENABLE_ADVANCED_CHARTS: bool = False


class MessagesJA:
    """日本語メッセージ定義"""

    # 共通メッセージ
    SUCCESS: str = "処理が正常に完了しました"
    ERROR: str = "エラーが発生しました"
    NOT_FOUND: str = "データが見つかりません"
    UNAUTHORIZED: str = "認証が必要です"
    FORBIDDEN: str = "アクセス権限がありません"

    # 認証関連
    LOGIN_SUCCESS: str = "ログインしました"
    LOGOUT_SUCCESS: str = "ログアウトしました"
    REGISTRATION_SUCCESS: str = "アカウントを作成しました"
    PASSWORD_RESET_SENT: str = "パスワードリセットメールを送信しました"

    # データ操作
    DATA_SAVED: str = "データを保存しました"
    DATA_DELETED: str = "データを削除しました"
    DATA_UPDATED: str = "データを更新しました"

    # お気に入り
    FAVORITE_ADDED: str = "お気に入りに追加しました"
    FAVORITE_REMOVED: str = "お気に入りから削除しました"

    # コメント
    COMMENT_POSTED: str = "コメントを投稿しました"
    COMMENT_DELETED: str = "コメントを削除しました"

    # エラーメッセージ
    INVALID_CREDENTIALS: str = "ユーザー名またはパスワードが正しくありません"
    EMAIL_ALREADY_EXISTS: str = "このメールアドレスは既に登録されています"
    USERNAME_ALREADY_EXISTS: str = "このユーザー名は既に使用されています"
    WEAK_PASSWORD: str = "パスワードが弱すぎます。より強力なパスワードを使用してください"

    # AI分析
    AI_ANALYSIS_STARTED: str = "AI分析を開始しました"
    AI_ANALYSIS_COMPLETED: str = "AI分析が完了しました"
    AI_ANALYSIS_FAILED: str = "AI分析に失敗しました"


class ValidationRules:
    """バリデーションルール"""

    # ユーザー名
    USERNAME_MIN_LENGTH: int = 3
    USERNAME_MAX_LENGTH: int = 50
    USERNAME_PATTERN: str = r"^[a-zA-Z0-9_-]+$"

    # メールアドレス
    EMAIL_PATTERN: str = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    # コメント
    COMMENT_MIN_LENGTH: int = 1
    COMMENT_MAX_LENGTH: int = 1000

    # 企業コード
    COMPANY_CODE_LENGTH: int = 4
    COMPANY_CODE_PATTERN: str = r"^\d{4}$"


# 設定のエクスポート
config = {
    "app": AppConfig,
    "security": SecurityConfig,
    "database": DatabaseConfig,
    "email": EmailConfig,
    "external_api": ExternalAPIConfig,
    "logging": LoggingConfig,
    "cache": CacheConfig,
    "ui": UIConfig,
    "features": FeatureFlags,
    "messages": MessagesJA,
    "validation": ValidationRules,
}


def get_config(section: str = None) -> Dict:
    """
    設定を取得する関数

    Args:
        section: 取得したい設定セクション名（指定しない場合は全設定）

    Returns:
        設定辞書
    """
    if section:
        return config.get(section, {})
    return config


def validate_required_env_vars() -> List[str]:
    """
    必須環境変数のチェック

    Returns:
        不足している環境変数のリスト
    """
    required_vars = [
        "SECRET_KEY",
        "GEMINI_API_KEY",
    ]

    missing = []
    for var in required_vars:
        if not os.getenv(var) or os.getenv(var) == "your-secret-key-placeholder":
            missing.append(var)

    return missing


if __name__ == "__main__":
    import sys
    import io

    # Windows環境での日本語出力対応
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    # 設定の検証
    print("=== Xserver株式分析 設定確認 ===\n")

    print(f"アプリケーション名: {AppConfig.APP_NAME}")
    print(f"バージョン: {AppConfig.APP_VERSION}")
    print(f"デフォルト言語: {AppConfig.DEFAULT_LANGUAGE}")
    print(f"タイムゾーン: {AppConfig.TIMEZONE}\n")

    # 必須環境変数のチェック
    missing_vars = validate_required_env_vars()
    if missing_vars:
        print("[WARNING] 以下の環境変数が設定されていません:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\n.envファイルを確認してください。\n")
    else:
        print("[OK] すべての必須環境変数が設定されています。\n")

    # 機能フラグの表示
    print("有効な機能:")
    if FeatureFlags.ENABLE_AI_ANALYSIS:
        print("  [OK] AI分析")
    if FeatureFlags.ENABLE_EMAIL_NOTIFICATIONS:
        print("  [OK] メール通知")
    if FeatureFlags.ENABLE_USER_COMMENTS:
        print("  [OK] ユーザーコメント")
    if FeatureFlags.ENABLE_SOCIAL_FEATURES:
        print("  [OK] ソーシャル機能")
    if FeatureFlags.ENABLE_PWA:
        print("  [OK] PWA（Progressive Web App）")
