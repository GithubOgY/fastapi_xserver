# Xserver VPS 練習用アプリ (FastAPI + htmx)

Xserver VPSへのデプロイを練習するための FastAPI + htmx アプリケーションです。
Docker + Docker Compose (Nginxリバースプロキシ構成) で動作するように設計されています。

## 技術スタック
- **Backend**: FastAPI (Python)
- **Frontend**: Jinja2 + htmx
- **Infrastructure**: Docker, Docker Compose, Nginx

## ローカル開発 (Pythonのみ)

Dockerを使わずに、ローカル環境で直接Pythonを実行して開発する場合の手順です。

1. 仮想環境の作成と有効化 (推奨):
   ```bash
   python -m venv venv
   # Windows
   .\venv\Scripts\activate
   # Mac/Linux
   source venv/bin/activate
   ```

2. 依存関係のインストール:
   ```bash
   pip install -r requirements.txt
   ```

3. 開発サーバーの起動:
   ```bash
   uvicorn main:app --reload
   ```

4. ブラウザでアクセス:
   `http://localhost:8000`

## VPSへのデプロイ (Docker使用)

Xserver VPS上でのデプロイ手順です。

1. リポジトリをクローン/プル:
   ```bash
   git pull origin main
   ```

2. Docker Compose で起動:
   ```bash
   docker compose up -d --build
   ```

3. アクセス確認:
   - URL: `https://site.y-project-vps.xyz` (SSL設定後)
   - HTTP: `http://site.y-project-vps.xyz`

## ディレクトリ構成
- `main.py`: FastAPIアプリケーションのエントリーポイント
- `templates/`: HTMLテンプレート (Jinja2)
- `nginx/`: Nginx設定ファイル
- `Dockerfile`: アプリケーションのDockerイメージ定義
- `docker-compose.yml`: サービス構成定義
