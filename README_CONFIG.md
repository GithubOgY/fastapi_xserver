# 初期設定ファイル - 使用方法

## 📁 作成されたファイル

以下の3つの設定ファイルを作成しました:

### 1. `config.py` - アプリケーション設定

アプリケーション全体の設定を一元管理するファイルです。

**主な機能:**
- 環境変数の読み込みと管理
- アプリケーション基本設定
- データベース接続設定
- 外部API設定（Gemini, EDINET, J-Quants）
- UI/UX設定
- 機能フラグ管理

**使用例:**

```python
from config import AppConfig, SecurityConfig, MessagesJA

# アプリケーション名を取得
app_name = AppConfig.APP_NAME  # "Xserver株式分析"

# デフォルト言語
language = AppConfig.DEFAULT_LANGUAGE  # "ja"

# セキュリティ設定
secret_key = SecurityConfig.SECRET_KEY
token_expire = SecurityConfig.ACCESS_TOKEN_EXPIRE_MINUTES

# 日本語メッセージ
success_msg = MessagesJA.SUCCESS  # "処理が正常に完了しました"
login_success = MessagesJA.LOGIN_SUCCESS  # "ログインしました"
```

**動作確認:**

```bash
python config.py
```

出力例:
```
=== Xserver株式分析 設定確認 ===

アプリケーション名: Xserver株式分析
バージョン: 1.0.0
デフォルト言語: ja
タイムゾーン: Asia/Tokyo

有効な機能:
  [OK] AI分析
  [OK] メール通知
  [OK] ユーザーコメント
```

---

### 2. `locale_ja.py` - 日本語メッセージ定義

アプリケーション全体で使用される日本語メッセージを管理します。

**主なカテゴリ:**
- `COMMON`: 共通メッセージ（保存、削除、キャンセルなど）
- `AUTH`: 認証・ログイン関連
- `NAV`: ナビゲーション
- `COMPANY`: 企業・銘柄情報
- `FINANCIAL`: 財務情報
- `STOCK`: 株価情報
- `AI_ANALYSIS`: AI分析関連
- `ERRORS`: エラーメッセージ

**使用例:**

```python
from locale_ja import Messages, msg, msgs

# 個別メッセージの取得
login_text = msg("AUTH", "login")  # "ログイン"
save_text = msg("COMMON", "save")  # "保存"
error_text = msg("ERRORS", "not_found")  # "ページが見つかりません"

# プレースホルダー付きメッセージ
time_msg = msg("TIME", "minutes_ago", n=5)  # "5分前"

# カテゴリ全体を取得
all_auth_msgs = msgs("AUTH")
# {'login': 'ログイン', 'logout': 'ログアウト', ...}
```

**テンプレートでの使用例:**

```python
from locale_ja import msg

# Jinja2テンプレート内
@app.route("/dashboard")
def dashboard():
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "messages": {
            "welcome": msg("COMMON", "welcome"),
            "dashboard": msg("NAV", "dashboard"),
            "favorites": msg("NAV", "favorites"),
        }
    })
```

---

### 3. `setup.py` - 初期セットアップスクリプト

アプリケーションの初回起動時に実行する初期設定スクリプトです。

**実行内容:**
1. ✅ 必要なディレクトリの作成
2. ✅ 依存パッケージのチェック
3. ✅ 環境変数ファイル（.env）の確認
4. ✅ データベース接続テスト
5. ✅ 設定ファイルの検証

**実行方法:**

```bash
python setup.py
```

**出力例:**

```
============================================================
       Xserver株式分析アプリケーション
       初期セットアップスクリプト
============================================================

============================================================
  1. ディレクトリ構造の確認
============================================================
[OK] ディレクトリ構造: OK

============================================================
  2. 依存パッケージの確認
============================================================
[OK] すべての依存パッケージがインストールされています

============================================================
  [OK] セットアップ完了
============================================================
すべてのチェックが正常に完了しました。

次のコマンドでアプリケーションを起動できます:
  Windowsの場合:
    start_dev.bat

アクセスURL: http://localhost:8000
```

---

## 🚀 使用開始手順

### 1. 初期セットアップの実行

```bash
# セットアップスクリプトを実行
python setup.py
```

### 2. 環境変数の設定

`.env`ファイルを編集して、以下の必須項目を設定:

```bash
# JWT認証用の秘密鍵（setup.pyで自動生成されます）
SECRET_KEY=<自動生成されたキー>

# Gemini AI APIキー（必須）
GEMINI_API_KEY=your-actual-api-key-here

# データベースURL（開発環境ではSQLite、本番ではPostgreSQL）
DATABASE_URL=sqlite:///./sql_app.db
```

### 3. 設定の確認

```bash
# 設定ファイルの動作確認
python config.py
```

### 4. アプリケーションの起動

```bash
# Windowsの場合
start_dev.bat

# Linux/Macの場合
uvicorn main:app --reload
```

---

## 📝 main.pyでの設定の使い方

既存の`main.py`に設定を統合する方法:

### 現在のコード（例）

```python
from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-keep-it-secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
```

### 設定ファイルを使用したコード

```python
from config import SecurityConfig, MessagesJA, AppConfig

# セキュリティ設定
SECRET_KEY = SecurityConfig.SECRET_KEY
ALGORITHM = SecurityConfig.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = SecurityConfig.ACCESS_TOKEN_EXPIRE_MINUTES

# アプリケーション情報
APP_NAME = AppConfig.APP_NAME
DEFAULT_LANGUAGE = AppConfig.DEFAULT_LANGUAGE
```

### レスポンスメッセージの日本語化

**Before:**
```python
@app.post("/login")
async def login():
    # ...
    return {"message": "ログインしました"}
```

**After:**
```python
from locale_ja import msg

@app.post("/login")
async def login():
    # ...
    return {"message": msg("AUTH", "login_success")}
```

---

## 🎨 設定のカスタマイズ

### 新しいメッセージの追加

`locale_ja.py`に新しいカテゴリやメッセージを追加:

```python
class Messages:
    # 既存のカテゴリ...

    # 新しいカテゴリを追加
    CUSTOM = {
        "my_message": "カスタムメッセージ",
        "greeting": "こんにちは、{name}さん",
    }
```

使用:
```python
custom_msg = msg("CUSTOM", "my_message")
greeting = msg("CUSTOM", "greeting", name="太郎")  # "こんにちは、太郎さん"
```

### 機能フラグの変更

`config.py`の`FeatureFlags`クラスで機能の有効/無効を切り替え:

```python
class FeatureFlags:
    ENABLE_AI_ANALYSIS: bool = True  # AI分析を有効化
    ENABLE_PORTFOLIO_TRACKING: bool = False  # ポートフォリオ追跡は無効
```

コード内での使用:
```python
from config import FeatureFlags

if FeatureFlags.ENABLE_AI_ANALYSIS:
    # AI分析機能を表示
    analyze_button.show()
```

---

## 🔧 トラブルシューティング

### エンコーディングエラー（Windows）

Windows環境で日本語が文字化けする場合:

```python
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

これは`config.py`と`setup.py`に既に含まれています。

### 環境変数が読み込まれない

1. `.env`ファイルがプロジェクトルートに存在するか確認
2. `python-dotenv`がインストールされているか確認
3. `.env`ファイルの権限を確認（読み取り可能か）

---

## 📚 関連ドキュメント

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - 詳細なセットアップガイド
- [DEPLOYMENT_NOTES.md](DEPLOYMENT_NOTES.md) - デプロイメント手順
- [DEV_RULES.md](DEV_RULES.md) - 開発ルール

---

## ✅ チェックリスト

初期設定が完了したら、以下を確認:

- [ ] `python setup.py`が正常に完了
- [ ] `.env`ファイルが存在し、必須項目が設定済み
- [ ] `python config.py`でエラーが出ない
- [ ] `SECRET_KEY`が自動生成または手動設定済み
- [ ] `GEMINI_API_KEY`が設定済み
- [ ] アプリケーションが起動する（`uvicorn main:app --reload`）

---

**最終更新日**: 2025年12月31日
