"""
初期セットアップスクリプト
Initial Setup Script for Xserver Stock Analysis Application

このスクリプトは、アプリケーションの初回起動時に実行される初期設定を行います。
- 環境変数のチェック
- データベースの初期化
- ログディレクトリの作成
- 必要なディレクトリ構造の確認
"""

import os
import sys
import secrets
from pathlib import Path
from typing import List, Tuple

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def print_header(text: str) -> None:
    """ヘッダーを表示"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def print_success(text: str) -> None:
    """成功メッセージを表示"""
    print(f"[OK] {text}")


def print_warning(text: str) -> None:
    """警告メッセージを表示"""
    print(f"[WARNING] {text}")


def print_error(text: str) -> None:
    """エラーメッセージを表示"""
    print(f"[ERROR] {text}")


def print_info(text: str) -> None:
    """情報メッセージを表示"""
    print(f"[INFO] {text}")


def create_directories() -> Tuple[int, List[str]]:
    """必要なディレクトリを作成"""
    directories = [
        "logs",
        "static/icons",
        "templates",
        "utils",
        "scripts",
        "__pycache__",
    ]

    created_dirs = []
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            created_dirs.append(directory)

    return len(created_dirs), created_dirs


def check_env_file() -> Tuple[bool, List[str]]:
    """環境変数ファイルのチェック"""
    env_file = Path(".env")
    env_example = Path(".env.example")

    missing_vars = []

    if not env_file.exists():
        print_warning(".envファイルが見つかりません")
        if env_example.exists():
            print_info(".env.exampleをコピーして.envを作成してください")
            return False, ["ENV_FILE_MISSING"]
        else:
            print_error(".env.exampleも見つかりません")
            return False, ["ENV_FILE_MISSING", "ENV_EXAMPLE_MISSING"]

    # 環境変数の読み込み
    from dotenv import load_dotenv
    load_dotenv()

    # 必須環境変数のチェック
    required_vars = {
        "SECRET_KEY": "JWT認証用の秘密鍵",
        "GEMINI_API_KEY": "Google Gemini APIキー",
        "DATABASE_URL": "データベース接続URL",
    }

    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value or value in ["your-secret-key-placeholder", "your-gemini-api-key-here"]:
            missing_vars.append(f"{var} ({description})")

    return len(missing_vars) == 0, missing_vars


def generate_secret_key() -> str:
    """セキュアなSECRET_KEYを生成"""
    return secrets.token_urlsafe(32)


def setup_env_file() -> bool:
    """環境変数ファイルのセットアップ"""
    env_file = Path(".env")
    env_example = Path(".env.example")

    # .envファイルが存在しない場合、.env.exampleからコピー
    if not env_file.exists():
        if env_example.exists():
            print_info(".env.exampleから.envを作成しています...")
            content = env_example.read_text(encoding="utf-8")

            # SECRET_KEYを自動生成
            new_secret_key = generate_secret_key()
            content = content.replace(
                "SECRET_KEY=your-secret-key-placeholder",
                f"SECRET_KEY={new_secret_key}"
            )

            env_file.write_text(content, encoding="utf-8")
            print_success(".envファイルを作成しました")
            print_warning("GEMINI_API_KEYなどの必須項目を設定してください")
            return True
        else:
            print_error(".env.exampleが見つかりません")
            return False

    return True


def check_database() -> bool:
    """データベース接続のチェック"""
    try:
        from database import engine
        from sqlalchemy import text

        with engine.connect() as connection:
            # 簡単な接続テスト
            connection.execute(text("SELECT 1"))
            return True
    except Exception as e:
        print_error(f"データベース接続エラー: {str(e)}")
        return False


def check_dependencies() -> Tuple[bool, List[str]]:
    """依存パッケージのチェック"""
    required_packages = [
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "passlib",
        "python-jose",
        "yfinance",
        "pandas",
        "python-dotenv",
        "google-generativeai",
    ]

    missing_packages = []

    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing_packages.append(package)

    return len(missing_packages) == 0, missing_packages


def display_welcome_message() -> None:
    """ウェルカムメッセージを表示"""
    print("\n" + "=" * 60)
    print("       Xserver株式分析アプリケーション       ")
    print("       初期セットアップスクリプト            ")
    print("=" * 60 + "\n")


def display_completion_message(all_passed: bool) -> None:
    """完了メッセージを表示"""
    if all_passed:
        print_header("[OK] セットアップ完了")
        print("すべてのチェックが正常に完了しました。")
        print("\n次のコマンドでアプリケーションを起動できます:")
        print("\n  Windowsの場合:")
        print("    start_dev.bat")
        print("\n  Linux/Macの場合:")
        print("    uvicorn main:app --reload")
        print("\nアクセスURL: http://localhost:8000")
        print()
    else:
        print_header("[WARNING] セットアップ未完了")
        print("いくつかの問題があります。上記のエラーを修正してください。")
        print()


def main() -> None:
    """メイン処理"""
    import sys
    import io

    # Windows環境での日本語出力対応
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    display_welcome_message()

    all_checks_passed = True

    # 1. ディレクトリ構造のチェック
    print_header("1. ディレクトリ構造の確認")
    created_count, created_dirs = create_directories()
    if created_count > 0:
        print_info(f"{created_count}個のディレクトリを作成しました:")
        for d in created_dirs:
            print(f"    - {d}")
    print_success("ディレクトリ構造: OK")

    # 2. 依存パッケージのチェック
    print_header("2. 依存パッケージの確認")
    deps_ok, missing_deps = check_dependencies()
    if deps_ok:
        print_success("すべての依存パッケージがインストールされています")
    else:
        print_error("以下のパッケージが見つかりません:")
        for pkg in missing_deps:
            print(f"    - {pkg}")
        print_info("\n次のコマンドでインストールしてください:")
        print("    pip install -r requirements.txt")
        all_checks_passed = False

    # 3. 環境変数ファイルのチェック
    print_header("3. 環境変数の確認")
    if not Path(".env").exists():
        setup_env_file()

    env_ok, missing_env_vars = check_env_file()
    if env_ok:
        print_success("すべての必須環境変数が設定されています")
    else:
        print_error("以下の環境変数が設定されていません:")
        for var in missing_env_vars:
            print(f"    - {var}")
        print_info("\n.envファイルを編集して設定してください")
        all_checks_passed = False

    # 4. データベース接続のチェック（依存パッケージがある場合のみ）
    if deps_ok and env_ok:
        print_header("4. データベース接続の確認")
        db_ok = check_database()
        if db_ok:
            print_success("データベース接続: OK")
        else:
            print_warning("データベース接続に失敗しました（初回起動時は正常です）")

    # 5. 設定ファイルのチェック
    print_header("5. 設定ファイルの確認")
    config_file = Path("config.py")
    if config_file.exists():
        print_success("config.py: 存在します")
        try:
            from config import validate_required_env_vars
            missing = validate_required_env_vars()
            if missing:
                print_warning(f"設定の警告: {', '.join(missing)}が未設定")
        except Exception as e:
            print_error(f"設定ファイル読み込みエラー: {str(e)}")
    else:
        print_error("config.pyが見つかりません")
        all_checks_passed = False

    # 完了メッセージ
    display_completion_message(all_checks_passed)

    # 終了コード
    sys.exit(0 if all_checks_passed else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nセットアップを中断しました。")
        sys.exit(1)
    except Exception as e:
        print_error(f"予期しないエラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
