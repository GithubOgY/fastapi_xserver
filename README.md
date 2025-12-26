# Xserver VPS 練習用アプリ (FastAPI + htmx)

Xserver VPSへのデプロイを練習するための FastAPI + htmx アプリケーションです。
Docker + Docker Compose (Nginxリバースプロキシ + SSL) で本番運用するように構成されています。

## 技術スタック
- **Backend**: FastAPI (Python 3.11)
- **Frontend**: Jinja2 + htmx (v2.0.0)
- **Design**: Vanilla CSS (Premium Glassmorphism)
- **Infrastructure**: Docker, Docker Compose, Nginx
- **Security**: Let's Encrypt (SSL/HTTPS)

## ローカル開発 (Dockerなし)

1. **環境構築**:
   ```bash
   .\start_dev.bat
   ```
   ※初回実行時に `venv` の作成と `pip install` が自動で行われます。

2. **手動起動**:
   ```bash
   uvicorn main:app --reload
   ```
   アクセス: [http://localhost:8000](http://localhost:8000)

## VPSへのデプロイ (Docker)

1. **コードの更新**:
   ```bash
   git pull
   ```

2. **起動とビルド**:
   ```bash
   docker compose up -d --build
   ```
   アクセス: [https://site.y-project-vps.xyz](https://site.y-project-vps.xyz)

## 主要な設定ファイル
- `main.py`: アプリケーションロジック（GET/HEAD/POST）
- `templates/index.html`: UIテンプレート
- `docker-compose.yml`: サービス定義（App:8000, Nginx:80/443）
- `nginx/default.conf`: リバースプロキシとSSL/HTTPSリダイレクト設定
- `Dockerfile`: アプリのビルド定義
