# Xserver株式分析アプリケーション - セットアップガイド

## 📋 目次

1. [概要](#概要)
2. [システム要件](#システム要件)
3. [初期セットアップ](#初期セットアップ)
4. [環境変数の設定](#環境変数の設定)
5. [データベースの初期化](#データベースの初期化)
6. [アプリケーションの起動](#アプリケーションの起動)
7. [トラブルシューティング](#トラブルシューティング)

---

## 概要

このガイドでは、Xserver株式分析アプリケーションの初期セットアップ手順を説明します。

### 主な機能

- 📊 日本株式市場の財務データ分析
- 🤖 AI（Google Gemini）による銘柄分析
- 📈 株価チャート・テクニカル分析
- 💬 ユーザーコミュニティ機能
- ⭐ お気に入り・ポートフォリオ管理
- 📱 PWA対応（オフライン利用可能）

---

## システム要件

### 必須環境

- **Python**: 3.9以上
- **pip**: 最新版
- **Node.js**: 14.x以上（PWA用の静的ファイル管理）
- **Git**: 2.x以上

### 推奨環境

- **OS**: Windows 10/11、macOS 10.15以上、Ubuntu 20.04以上
- **メモリ**: 4GB以上
- **ストレージ**: 1GB以上の空き容量

---

## 初期セットアップ

### 1. リポジトリのクローン

```bash
git clone <リポジトリURL>
cd xserver_app
```

### 2. 仮想環境の作成（推奨）

**Windows:**
```batch
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 4. 初期セットアップスクリプトの実行

```bash
python setup.py
```

このスクリプトは以下を自動で実行します:

- ✅ 必要なディレクトリの作成
- ✅ 依存パッケージのチェック
- ✅ 環境変数ファイルの確認
- ✅ データベース接続テスト
- ✅ 設定ファイルの検証

---

## 環境変数の設定

### `.env`ファイルの作成

初回セットアップ時、`.env.example`から`.env`が自動作成されます。
以下の必須項目を設定してください。

### 必須環境変数

```bash
# セキュリティ設定
SECRET_KEY=<自動生成されたキー>  # JWTトークン用の秘密鍵

# Gemini AI APIキー（必須）
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL=gemini-2.0-flash

# データベース設定
DATABASE_URL=sqlite:///./sql_app.db  # 開発環境（SQLite）
# DATABASE_URL=postgresql://user:pass@localhost/stock_db  # 本番環境（PostgreSQL）
```

### オプション環境変数

```bash
# メール送信設定（パスワードリセット機能用）
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_FROM=your-email@gmail.com

# 外部API
EDINET_API_KEY=<EDINETのAPIキー>  # 金融庁の企業開示情報
JQUANTS_API_KEY=<J-QuantsのAPIキー>  # 日本取引所の株価データ

# ログ設定
LOG_DIR=logs
LOG_LEVEL=INFO
```

### APIキーの取得方法

#### 1. Gemini APIキー（必須）

1. [Google AI Studio](https://makersuite.google.com/app/apikey)にアクセス
2. Googleアカウントでログイン
3. 「Get API Key」をクリック
4. 生成されたキーを`.env`の`GEMINI_API_KEY`に設定

#### 2. EDINET APIキー（オプション）

1. [EDINET API利用登録](https://disclosure2.edinet-fsa.go.jp/)にアクセス
2. 利用規約に同意して登録
3. 発行されたAPIキーを`.env`に設定

#### 3. J-Quants APIキー（オプション）

1. [J-Quants](https://japanexchangegroup.com/jquants/)にアクセス
2. アカウント登録（無料プランあり）
3. APIキーを取得して`.env`に設定

---

## データベースの初期化

### SQLite（開発環境・デフォルト）

特別な設定は不要です。アプリケーション起動時に自動で`sql_app.db`が作成されます。

```bash
# 自動で作成されるため、特別な操作は不要
```

### PostgreSQL（本番環境）

Docker Composeを使用する場合:

```bash
# docker-compose.ymlを使用してPostgreSQLを起動
docker-compose up -d db

# .envファイルのDATABASE_URLを変更
DATABASE_URL=postgresql://user:password@localhost:5432/stock_db
```

手動でPostgreSQLをセットアップする場合:

```sql
CREATE DATABASE stock_db;
CREATE USER stock_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE stock_db TO stock_user;
```

---

## アプリケーションの起動

### 開発環境（ホットリロード有効）

**Windows:**
```batch
start_dev.bat
```

**Linux/Mac:**
```bash
uvicorn main:app --reload
```

### 本番環境（Docker）

```bash
docker-compose up -d
```

### アクセス方法

アプリケーション起動後、以下のURLにアクセス:

- **ローカル開発**: http://localhost:8000
- **本番環境**: https://your-domain.com

### 初回ログイン

デフォルトの管理者アカウント:

- **ユーザー名**: `admin`
- **パスワード**: `.env`の`ADMIN_PASSWORD`で設定した値

⚠️ **セキュリティ上重要**: 本番環境では必ず強力なパスワードに変更してください。

---

## 設定ファイルの説明

### `config.py`

アプリケーション全体の設定を管理します。

```python
from config import AppConfig, SecurityConfig, MessagesJA

# アプリケーション設定の取得
app_name = AppConfig.APP_NAME
default_language = AppConfig.DEFAULT_LANGUAGE

# 日本語メッセージの使用
login_message = MessagesJA.LOGIN_SUCCESS
```

主な設定クラス:

- `AppConfig`: アプリケーション基本設定
- `SecurityConfig`: セキュリティ・認証設定
- `DatabaseConfig`: データベース設定
- `EmailConfig`: メール送信設定
- `ExternalAPIConfig`: 外部API設定
- `UIConfig`: UI/UX設定
- `MessagesJA`: 日本語メッセージ定義

### `locale_ja.py`

UI表示用の日本語メッセージを管理します。

```python
from locale_ja import Messages, msg

# メッセージの取得
welcome_msg = msg("COMMON", "welcome")
login_success = msg("AUTH", "login_success")
```

---

## トラブルシューティング

### よくある問題と解決方法

#### 1. `ModuleNotFoundError: No module named 'fastapi'`

**原因**: 依存パッケージがインストールされていない

**解決方法**:
```bash
pip install -r requirements.txt
```

#### 2. `SECRET_KEY is not set`

**原因**: 環境変数が設定されていない

**解決方法**:
1. `.env`ファイルが存在するか確認
2. `SECRET_KEY`が設定されているか確認
3. `python setup.py`を再実行

#### 3. データベース接続エラー

**原因**: データベースURLが正しくない、またはデータベースが起動していない

**解決方法**:
```bash
# SQLiteの場合（デフォルト）
# DATABASE_URL=sqlite:///./sql_app.db を確認

# PostgreSQLの場合
docker-compose up -d db
# または手動でPostgreSQLを起動
```

#### 4. Gemini API エラー: `API key not valid`

**原因**: APIキーが正しくない、または設定されていない

**解決方法**:
1. `.env`の`GEMINI_API_KEY`を確認
2. [Google AI Studio](https://makersuite.google.com/app/apikey)で新しいキーを取得
3. APIキーにスペースや改行が含まれていないか確認

#### 5. ポート8000が既に使用されている

**原因**: 別のアプリケーションがポート8000を使用中

**解決方法**:
```bash
# 別のポートで起動
uvicorn main:app --reload --port 8080

# または使用中のプロセスを終了
# Windows
netstat -ano | findstr :8000
taskkill /PID <プロセスID> /F

# Linux/Mac
lsof -ti:8000 | xargs kill -9
```

#### 6. Service Worker 404エラー

**原因**: Service Workerのキャッシュが古い

**解決方法**:
1. ブラウザのDevTools → Application → Service Workers
2. "Unregister"をクリック
3. Cache Storage → "xstock-v1"を削除
4. ページをハードリロード（Ctrl+Shift+R）

---

## 次のステップ

### ✅ セットアップ完了後

1. **管理画面にアクセス**: http://localhost:8000/admin
2. **初期データの投入**: 企業データの同期を実行
3. **ユーザーアカウントの作成**: 新規登録機能でテストユーザーを作成
4. **AI分析の動作確認**: 銘柄ページでAI分析を実行

### 📚 参考ドキュメント

- [DEPLOYMENT_NOTES.md](DEPLOYMENT_NOTES.md) - デプロイメント手順
- [DEV_RULES.md](DEV_RULES.md) - 開発ルール
- [ROADMAP.md](ROADMAP.md) - 機能ロードマップ
- [EDINET_API_GUIDE.md](EDINET_API_GUIDE.md) - EDINET API使用方法

### 🤝 サポート

問題が解決しない場合は、以下を確認してください:

1. `logs/app.log`のエラーログ
2. ブラウザのコンソールログ（F12）
3. Python環境とパッケージバージョン

---

## ライセンス

このプロジェクトは MIT License の下で公開されています。

## 貢献

バグ報告や機能リクエストは、GitHubのIssuesでお願いします。

---

**最終更新**: 2025年12月31日
