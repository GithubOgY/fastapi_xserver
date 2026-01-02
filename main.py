from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Query, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, func
from database import SessionLocal, CompanyFundamental, User, Company, UserFavorite, StockComment, UserProfile, UserFollow, AIAnalysisCache, CommentLike, AuditLog
from utils.mail_sender import send_email
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import sys
import logging
import time
import json
import asyncio
import html
import requests
import urllib.parse
import yfinance as yf
import pandas as pd
from utils.edinet_enhanced import get_financial_history, format_financial_data, search_company_reports, process_document

from utils.growth_analysis import analyze_growth_quality
from utils.ai_analysis import analyze_stock_with_ai, analyze_financial_health, analyze_business_competitiveness, analyze_risk_governance, analyze_dashboard_image
from utils.premium import get_user_tier, get_tier_display_name, get_tier_badge_html, has_feature_access, get_feature_limit, is_premium_active, get_ai_usage_today, increment_ai_usage, check_ai_usage_limit
from utils.technical_analysis import calculate_all_indicators, get_latest_values
from utils.chart_data import format_chartjs_data, calculate_period_days

# Load environment variables
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-keep-it-secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")
LOG_DIR = os.getenv("LOG_DIR", "logs")

# --- Logging Configuration ---
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logger = logging.getLogger("fastapi-app")
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    file_handler = logging.FileHandler(f"{LOG_DIR}/app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

logging.getLogger("uvicorn.access").addHandler(logging.FileHandler(f"{LOG_DIR}/app.log"))

from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from utils.jquants_api import sync_companies_to_db
import asyncio

app = FastAPI()

async def background_sync_jquants():
    """Run J-Quants sync in background"""
    logger.info("[Startup] Starting J-Quants data sync to populate scale categories...")
    try:
        # Run synchronous function in thread pool
        result = await run_in_threadpool(sync_companies_to_db)
        logger.info(f"[Startup] J-Quants sync finished. Result: {result}")
    except Exception as e:
        logger.error(f"[Startup] J-Quants sync failed: {e}")

@app.on_event("startup")
async def startup_event():
    """Unified startup tasks: migration, initial data, and initialization"""
    logger.info("Application starting up...")
    
    # 1. DB Migration Check
    try:
        from database import engine
        from sqlalchemy import text
        with engine.connect() as connection:
            # Check scale_category
            try:
                connection.execute(text("SELECT scale_category FROM companies LIMIT 1"))
            except Exception:
                logger.info("[Migration] 'scale_category' column missing. Adding it...")
                connection.execute(text("ALTER TABLE companies ADD COLUMN scale_category VARCHAR"))
                logger.info("[Migration] Successfully added 'scale_category' column.")
            
            # Check last_sync columns
            try:
                connection.execute(text("SELECT last_sync_at FROM companies LIMIT 1"))
            except Exception:
                logger.info("[Migration] 'last_sync' columns missing. Adding them...")
                connection.execute(text("ALTER TABLE companies ADD COLUMN last_sync_at VARCHAR"))
                connection.execute(text("ALTER TABLE companies ADD COLUMN last_sync_error VARCHAR"))
                logger.info("[Migration] Successfully added last_sync columns.")
            
            # Check is_admin column
            try:
                connection.execute(text("SELECT is_admin FROM users LIMIT 1"))
            except Exception:
                logger.info("[Migration] 'is_admin' column missing. Adding it...")
                connection.execute(text("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0"))
                logger.info("[Migration] Successfully added 'is_admin' column.")

            # Check ai_analysis_history table (Phase 2)
            try:
                connection.execute(text("SELECT id FROM ai_analysis_history LIMIT 1"))
            except Exception:
                logger.info("[Migration] 'ai_analysis_history' table missing. Creating it...")
                # Create table with proper schema
                if DATABASE_URL.startswith("sqlite"):
                    connection.execute(text("""
                        CREATE TABLE ai_analysis_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            ticker_code VARCHAR(20) NOT NULL,
                            analysis_type VARCHAR(50) DEFAULT 'visual',
                            analysis_json TEXT NOT NULL,
                            overall_score INTEGER,
                            investment_rating VARCHAR(20),
                            score_profitability INTEGER,
                            score_growth INTEGER,
                            score_financial_health INTEGER,
                            score_cash_generation INTEGER,
                            score_capital_efficiency INTEGER,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                    # Create indexes
                    connection.execute(text("CREATE INDEX idx_ah_ticker ON ai_analysis_history(ticker_code)"))
                    connection.execute(text("CREATE INDEX idx_ah_type ON ai_analysis_history(analysis_type)"))
                    connection.execute(text("CREATE INDEX idx_ah_created ON ai_analysis_history(created_at)"))
                    connection.execute(text("CREATE INDEX idx_ah_score ON ai_analysis_history(overall_score)"))
                else:  # PostgreSQL
                    connection.execute(text("""
                        CREATE TABLE ai_analysis_history (
                            id SERIAL PRIMARY KEY,
                            ticker_code VARCHAR(20) NOT NULL,
                            analysis_type VARCHAR(50) DEFAULT 'visual',
                            analysis_json TEXT NOT NULL,
                            overall_score INTEGER,
                            investment_rating VARCHAR(20),
                            score_profitability INTEGER,
                            score_growth INTEGER,
                            score_financial_health INTEGER,
                            score_cash_generation INTEGER,
                            score_capital_efficiency INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                    # Create indexes
                    connection.execute(text("CREATE INDEX idx_ah_ticker ON ai_analysis_history(ticker_code)"))
                    connection.execute(text("CREATE INDEX idx_ah_type ON ai_analysis_history(analysis_type)"))
                    connection.execute(text("CREATE INDEX idx_ah_created ON ai_analysis_history(created_at)"))
                    connection.execute(text("CREATE INDEX idx_ah_score ON ai_analysis_history(overall_score)"))
                logger.info("[Migration] Successfully created 'ai_analysis_history' table with indexes.")

            # Check audit_logs table
            try:
                connection.execute(text("SELECT id FROM audit_logs LIMIT 1"))
                logger.info("[Migration] 'audit_logs' table exists.")
            except Exception:
                logger.info("[Migration] 'audit_logs' table missing. Creating it...")
                if DATABASE_URL.startswith("sqlite"):
                    connection.execute(text("""
                        CREATE TABLE audit_logs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            action_type VARCHAR(50) NOT NULL,
                            action_category VARCHAR(20) NOT NULL,
                            user_id INTEGER,
                            username VARCHAR(50),
                            ip_address VARCHAR(45),
                            user_agent VARCHAR(255),
                            target_type VARCHAR(50),
                            target_id INTEGER,
                            target_description VARCHAR(200),
                            details TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                        )
                    """))
                    # Create indexes
                    connection.execute(text("CREATE INDEX idx_audit_action_type ON audit_logs(action_type)"))
                    connection.execute(text("CREATE INDEX idx_audit_category ON audit_logs(action_category)"))
                    connection.execute(text("CREATE INDEX idx_audit_user_id ON audit_logs(user_id)"))
                    connection.execute(text("CREATE INDEX idx_audit_ip ON audit_logs(ip_address)"))
                    connection.execute(text("CREATE INDEX idx_audit_created ON audit_logs(created_at)"))
                    connection.execute(text("CREATE INDEX idx_audit_target ON audit_logs(target_type, target_id)"))
                else:  # PostgreSQL
                    connection.execute(text("""
                        CREATE TABLE audit_logs (
                            id SERIAL PRIMARY KEY,
                            action_type VARCHAR(50) NOT NULL,
                            action_category VARCHAR(20) NOT NULL,
                            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                            username VARCHAR(50),
                            ip_address VARCHAR(45),
                            user_agent VARCHAR(255),
                            target_type VARCHAR(50),
                            target_id INTEGER,
                            target_description VARCHAR(200),
                            details TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                        )
                    """))
                    # Create indexes
                    connection.execute(text("CREATE INDEX idx_audit_action_type ON audit_logs(action_type)"))
                    connection.execute(text("CREATE INDEX idx_audit_category ON audit_logs(action_category)"))
                    connection.execute(text("CREATE INDEX idx_audit_user_id ON audit_logs(user_id)"))
                    connection.execute(text("CREATE INDEX idx_audit_ip ON audit_logs(ip_address)"))
                    connection.execute(text("CREATE INDEX idx_audit_created ON audit_logs(created_at)"))
                    connection.execute(text("CREATE INDEX idx_audit_target ON audit_logs(target_type, target_id)"))
                logger.info("[Migration] Successfully created 'audit_logs' table with indexes.")

            # Commit changes if not autocommited
            connection.commit()
    except Exception as e:
        logger.warning(f"[Migration] Startup migration check failed: {e}")
    
    # 2. Initial Data Setup
    db = SessionLocal()
    try:
        # Admin user
        if db.query(User).count() == 0:
            admin_user = User(username=ADMIN_USERNAME, hashed_password=get_hashed_password(ADMIN_PASSWORD), is_admin=1)
            db.add(admin_user)
            db.commit()
            logger.info(f"Created initial admin user: {ADMIN_USERNAME}")
        else:
            admin = db.query(User).filter(User.username == ADMIN_USERNAME).first()
            if admin and not admin.is_admin:
                admin.is_admin = 1
                db.commit()
                logger.info(f"Ensured admin status for: {ADMIN_USERNAME}")
        
        # Initial companies
        if db.query(Company).count() == 0:
            initial_companies = {
                "7203.T": "トヨタ自動車",
                "6758.T": "ソニーグループ",
                "9984.T": "ソフトバンクグループ"
            }
            for ticker, name in initial_companies.items():
                db.add(Company(ticker=ticker, name=name))
            db.commit()
            logger.info("Added initial companies.")
    except Exception as e:
        logger.error(f"Initial data setup error: {e}")
    finally:
        db.close()
    
    # 3. Background Tasks
    asyncio.create_task(background_sync_jquants())

# Mount static files for PWA support
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Middleware for Request Logging ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(
        f"{request.client.host} - \"{request.method} {request.url.path}\" "
        f"{response.status_code} ({process_time:.4f}s)"
    )
    return response

templates = Jinja2Templates(directory="templates")

# Add custom Jinja2 filters for premium features
templates.env.filters['get_user_tier'] = get_user_tier
templates.env.filters['get_tier_badge_html'] = get_tier_badge_html
templates.env.filters['get_tier_display_name'] = get_tier_display_name

# ヘルパー関数
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def fetch_edinet_background(ticker_code: str):
    """
    Background task to fetch and cache EDINET data.
    """
    try:
        logger.info(f"[BG-TASK] Starting background fetch for: {ticker_code}")
        clean_code = ticker_code.replace(".T", "")
        # Check if it's a valid 4-digit code
        if len(clean_code) == 4 and clean_code.isdigit():
            logger.info(f"[BG-TASK] Valid 4-digit code: {clean_code}. Calling get_financial_history...")
            # Using a new database session if needed handled inside, or relying on auto-session
            # Note: get_financial_history uses SessionLocal internally for caching
            result = get_financial_history(company_code=clean_code, years=3)
            logger.info(f"[BG-TASK] fetch completed for {clean_code}. Result count: {len(result)}")
        else:
            logger.warning(f"[BG-TASK] Invalid code format: {ticker_code} -> {clean_code}")
    except Exception as e:
        logger.error(f"[BG-TASK] Background fetch failed for {ticker_code}: {e}", exc_info=True)

import bcrypt

def verify_password(plain_password, hashed_password):
    # bcrypt has a 72-byte limit
    password_bytes = plain_password[:72].encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8') if isinstance(hashed_password, str) else hashed_password
    return bcrypt.checkpw(password_bytes, hashed_bytes)

def get_hashed_password(password):
    # bcrypt has a 72-byte limit
    password_bytes = password[:72].encode('utf-8')
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        user = db.query(User).filter(User.username == username).first()
        return user
    except JWTError:
        return None


async def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    """Get current user if logged in, None otherwise (no redirect)"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        user = db.query(User).filter(User.username == username).first()
        return user
    except JWTError:
        return None


# --- Audit Log Helper Functions ---
def get_client_ip(request: Request) -> Optional[str]:
    """
    リクエストからクライアントIPアドレスを取得
    プロキシ経由の場合は X-Forwarded-For ヘッダーを優先
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return None


def get_user_agent(request: Request) -> Optional[str]:
    """User-Agentヘッダーを取得（最大255文字）"""
    ua = request.headers.get("User-Agent", "")
    return ua[:255] if ua else None


async def create_audit_log(
    db: Session,
    action_type: str,
    action_category: str,
    request: Request,
    user: Optional[User] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    target_description: Optional[str] = None,
    details: Optional[dict] = None
):
    """
    監査ログを作成

    Args:
        db: データベースセッション
        action_type: アクション種別（LOGIN_SUCCESS, USER_DELETE など）
        action_category: カテゴリ（AUTH, ADMIN, MODERATION）
        request: FastAPIリクエストオブジェクト
        user: 実行ユーザー（オプション）
        target_type: 対象リソースタイプ（オプション）
        target_id: 対象リソースID（オプション）
        target_description: 対象の説明（オプション）
        details: 追加情報の辞書（オプション、JSONとして保存）
    """
    try:
        audit_log = AuditLog(
            action_type=action_type,
            action_category=action_category,
            user_id=user.id if user else None,
            username=user.username if user else None,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            target_type=target_type,
            target_id=target_id,
            target_description=target_description,
            details=json.dumps(details, ensure_ascii=False) if details else None
        )
        db.add(audit_log)
        db.commit()

        logger.info(
            f"[AUDIT] {action_type} | User: {user.username if user else 'Anonymous'} | "
            f"IP: {get_client_ip(request)} | Target: {target_type}#{target_id if target_id else 'N/A'}"
        )
    except Exception as e:
        logger.error(f"Failed to create audit log: {e}")
        db.rollback()


def create_audit_log_sync(
    db: Session,
    action_type: str,
    action_category: str,
    ip_address: Optional[str],
    user_agent: Optional[str],
    user: Optional[User] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    target_description: Optional[str] = None,
    details: Optional[dict] = None
):
    """同期版の監査ログ作成（バックグラウンドタスク用）"""
    try:
        audit_log = AuditLog(
            action_type=action_type,
            action_category=action_category,
            user_id=user.id if user else None,
            username=user.username if user else None,
            ip_address=ip_address,
            user_agent=user_agent,
            target_type=target_type,
            target_id=target_id,
            target_description=target_description,
            details=json.dumps(details, ensure_ascii=False) if details else None
        )
        db.add(audit_log)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to create audit log (sync): {e}")
        db.rollback()


# --- Yahoo Finance Data Fetching ---
def sync_stock_data(db: Session, target_ticker: Optional[str] = None):
    # 特定の銘柄、または全銘柄
    if target_ticker:
        tickers = [target_ticker]
    else:
        tickers = ["7203.T", "6758.T", "9984.T"]
        
    logger.info(f"Starting sync for tickers: {tickers}")
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for ticker_symbol in tickers:
        company = db.query(Company).filter(Company.ticker == ticker_symbol).first()
        if not company:
            company = Company(ticker=ticker_symbol, name=ticker_symbol)
            db.add(company)
            db.commit()

        try:
            logger.info(f"Refreshing data for {ticker_symbol}...")
            ticker = yf.Ticker(ticker_symbol)
            
            # 財務データの取得 - income_stmt を優先、fallback で financials
            financials = None
            try:
                financials = ticker.income_stmt
                if financials is None or financials.empty:
                    financials = ticker.financials
            except Exception as fetch_e:
                logger.warning(f"income_stmt failed for {ticker_symbol}, trying financials: {str(fetch_e)}")
                financials = ticker.financials
            
            if financials is None or financials.empty:
                error_msg = "API制限(429)またはデータ未検出"
                logger.warning(f"{error_msg} for {ticker_symbol}")
                company.last_sync_at = now_str
                company.last_sync_error = error_msg
                db.commit()
                continue
            
            df = financials.T
            for date, row in df.iterrows():
                try:
                    year = date.year
                    # データの抽出
                    revenue_raw = row.get('Total Revenue') or row.get('TotalRevenue') or 0
                    op_income_raw = row.get('Operating Income') or row.get('OperatingIncome') or 0
                    net_income_raw = row.get('Net Income Common Stockholders') or row.get('NetIncomeCommonStockholders') or row.get('Net Income') or 0
                    eps_raw = row.get('Basic EPS') or row.get('BasicEPS') or 0
                    
                    revenue = float(revenue_raw) / 1e8 if not pd.isna(revenue_raw) else 0
                    op_income = float(op_income_raw) / 1e8 if not pd.isna(op_income_raw) else 0
                    net_income = float(net_income_raw) / 1e8 if not pd.isna(net_income_raw) else 0
                    eps = float(eps_raw) if not pd.isna(eps_raw) else 0

                    existing = db.query(CompanyFundamental).filter(
                        CompanyFundamental.ticker == ticker_symbol,
                        CompanyFundamental.year == year
                    ).first()
                    
                    if existing:
                        existing.revenue = revenue
                        existing.operating_income = op_income
                        existing.net_income = net_income
                        existing.eps = eps
                    else:
                        db.add(CompanyFundamental(
                            ticker=ticker_symbol,
                            year=int(year),
                            revenue=revenue,
                            operating_income=op_income,
                            net_income=net_income,
                            eps=eps
                        ))
                    db.commit()
                except Exception as row_e:
                    logger.error(f"Row error for {ticker_symbol} {date}: {str(row_e)}")
                    db.rollback()
            
            company.last_sync_at = now_str
            company.last_sync_error = None # 成功
            db.commit()
            logger.info(f"Successfully synced {ticker_symbol}")
            time.sleep(1)
            
        except Exception as e:
            error_msg = f"同期エラー: {str(e)[:50]}"
            logger.error(f"Major error for {ticker_symbol}: {str(e)}")
            db.rollback()
            try:
                # Re-fetch company to ensure attached to session after rollback if needed, 
                # or just rely on session expiry. 
                # Safety: Re-query to be sure.
                company = db.query(Company).filter(Company.ticker == ticker_symbol).first()
                if company:
                    company.last_sync_at = now_str
                    company.last_sync_error = error_msg
                    db.commit()
            except Exception as secondary_e:
                logger.error(f"Failed to update error status for {ticker_symbol}: {secondary_e}")
                db.rollback()
# --- Routes & Endpoints ---
@app.get("/demo", response_class=HTMLResponse)
async def demo(request: Request):
    return templates.TemplateResponse("demo.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, current_user: User = Depends(get_current_user)):
    # ログイン済みならダッシュボードへリダイレクト
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    # 未ログインならランディングページを表示
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/offline", response_class=HTMLResponse)
async def offline_page(request: Request):
    """Offline fallback page for PWA"""
    return templates.TemplateResponse("offline.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, 
                    ticker: str = Query("7203.T"),
                    code: str = Query(None),
                    db: Session = Depends(get_db), 
                    current_user: User = Depends(get_current_user)):
    
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Read last searched ticker from cookie
    last_ticker = request.cookies.get("last_ticker", "")
    
    # Override from query param (e.g. from catalog)
    if code:
        last_ticker = code
    
    fundamentals = db.query(CompanyFundamental).filter(CompanyFundamental.ticker == ticker).order_by(CompanyFundamental.year.desc()).all()
    company = db.query(Company).filter(Company.ticker == ticker).first()
    ticker_display = company.name if company else ticker
    
    all_companies = db.query(Company).all()
    ticker_list = [{"code": c.ticker, "name": c.name} for c in all_companies]
    
    # Get user's favorites
    user_favorites = db.query(UserFavorite).filter(UserFavorite.user_id == current_user.id).all()
    favorite_tickers = [f.ticker for f in user_favorites]
    is_favorite = ticker in favorite_tickers
    
    # Get favorite companies with names for quick access
    favorite_companies = []
    for fav in user_favorites:
        comp = db.query(Company).filter(Company.ticker == fav.ticker).first()
        if comp:
            favorite_companies.append({"code": comp.ticker, "name": comp.name})

    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "fundamentals": fundamentals,
            "company": company,
            "ticker_name": f"{ticker} {ticker_display}",
            "current_ticker": ticker,
            "ticker_list": ticker_list,
            "user": current_user,
            "is_favorite": is_favorite,
            "favorite_companies": favorite_companies,
            "last_ticker": last_ticker
        }
    )

@app.get("/edinet", response_class=HTMLResponse)
async def edinet_page(request: Request, 
                      code: str = Query(None),
                      db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """EDINET enterprise financial search page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Read last EDINET search query from cookie
    last_query = request.cookies.get("last_edinet_query", "")

    # OGP Defaults
    og_title = "EDINET 企業財務検索 | X-Stock Analyzer"
    og_description = "有価証券報告書から公式財務データを取得し、詳細な分析を行います。"
    og_url = str(request.url)

    if code:
        clean_code = code.replace(".T", "")
        # Try to find name from DB (assuming 4 digit code match)
        # We verify if clean_code is digits to avoid SQL errors or odd lookups
        if clean_code.isdigit():
             comp_obj = db.query(Company).filter(Company.ticker.like(f"{clean_code}%")).first()
             if comp_obj:
                 title_name = comp_obj.name
             else:
                 title_name = f"コード {clean_code}"
             
             og_title = f"{title_name} - 財務分析レポート | X-Stock Analyzer"
             og_description = f"{title_name} の有価証券報告書に基づく詳細な財務指標、過去5年の業績推移、およびAIによる分析レポートを確認できます。"

    return templates.TemplateResponse(
        "edinet.html", 
        {
            "request": request, 
            "user": current_user,
            "last_query": last_query,
            "og_title": og_title,
            "og_description": og_description,
            "og_url": og_url
        }
    )

from sqlalchemy import func

@app.get("/catalog", response_class=HTMLResponse)
async def catalog_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
         return RedirectResponse(url="/login", status_code=303)
         
    # Get distinct sectors ordered by company count
    sectors_data = db.query(Company.sector_33, func.count(Company.ticker))\
        .filter(Company.sector_33 != None)\
        .group_by(Company.sector_33)\
        .order_by(func.count(Company.ticker).desc())\
        .all()
        
    sectors = [s[0] for s in sectors_data]
    
    return templates.TemplateResponse("catalog.html", {"request": request, "sectors": sectors})

@app.get("/api/companies/filter", response_class=HTMLResponse)
async def filter_companies(
    sector_33: str = Query(...),
    scale_category: str = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Company).filter(Company.sector_33 == sector_33)
    
    if scale_category:
        query = query.filter(Company.scale_category.like(f"%{scale_category}%"))
        
    companies = query.order_by(Company.scale_category, Company.code_4digit).all()
    
    if not companies:
        return "<div class='col-span-full text-center text-gray-500 py-4'>該当する企業は見つかりませんでした</div>"
        
    html = ""
    for c in companies:
        # Scale Badge
        scale_badge = ""
        if c.scale_category:
            s_raw = c.scale_category
            color = "gray"
            text = s_raw
            if "Core30" in s_raw: color = "red"; text="Core30"
            elif "Large70" in s_raw: color = "orange"; text="Large70"
            elif "Mid400" in s_raw: color = "yellow"; text="Mid400"
            elif "Small" in s_raw: color = "green"; text="Small"
            
            # Use style directly to avoid purgecss issues if any, matching main.py logic
            # Actually we use Tailwind classes normally available
            scale_badge = f'<span class="text-[10px] px-1.5 py-0.5 rounded bg-{color}-500/10 text-{color}-400 border border-{color}-500/20">{text}</span>'

        # Link to Dashboard with auto-fill params
        # Use code query param which is handled by dashboard (index.html) JS
        link = f"/dashboard?code={c.code_4digit}"
        
        html += f"""
        <a href="{link}" class="company-card group">
            <div class="flex flex-col">
                <div class="flex items-center gap-2">
                    <span class="font-bold text-gray-200 group-hover:text-indigo-400 transition-colors">{c.name}</span>
                    <span class="text-xs text-gray-500 font-mono">{c.code_4digit}</span>
                </div>
                <div class="flex items-center gap-2 mt-1">
                    {scale_badge}
                </div>
            </div>
            <span class="text-gray-600 group-hover:text-indigo-400">→</span>
        </a>
        """
    return html

@app.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request, 
                       tickers: str = Query(""),
                       db: Session = Depends(get_db), 
                       current_user: User = Depends(get_current_user)):
    
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    all_companies = db.query(Company).all()
    ticker_list = [{"code": c.ticker, "name": c.name} for c in all_companies]
    
    # Parse selected tickers
    selected_tickers = [t.strip() for t in tickers.split(",") if t.strip()] if tickers else []
    
    # Get comparison data
    comparison_data = []
    for ticker in selected_tickers[:4]:  # Max 4 stocks
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if company:
            fundamentals = db.query(CompanyFundamental).filter(
                CompanyFundamental.ticker == ticker
            ).order_by(CompanyFundamental.year.desc()).limit(5).all()
            
            # Convert to dict for JSON serialization
            fundamentals_data = []
            for f in fundamentals:
                fundamentals_data.append({
                    "year": f.year,
                    "revenue": f.revenue,
                    "operating_income": f.operating_income,
                    "net_income": f.net_income,
                    "eps": f.eps
                })
            
            comparison_data.append({
                "ticker": ticker,
                "name": company.name,
                "fundamentals": fundamentals_data
            })
    
    return templates.TemplateResponse(
        "compare.html", 
        {
            "request": request, 
            "user": current_user,
            "ticker_list": ticker_list,
            "selected_tickers": selected_tickers,
            "comparison_data": comparison_data
        }
    )

@app.get("/screener", response_class=HTMLResponse)
async def screener_page(request: Request, current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse("screener.html", {"request": request, "user": current_user})

@app.get("/api/screener/results", response_class=HTMLResponse)
async def screener_results(
    request: Request,
    keyword: str = Query(None),
    min_revenue: str = Query(None), # Receive as str to handle empty strings
    min_income: str = Query(None), # Receive as str to handle empty strings
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Convert empty strings to None and parse floats
    revenue_filter = float(min_revenue) if min_revenue and min_revenue.strip() else None
    income_filter = float(min_income) if min_income and min_income.strip() else None

    # Base query
    query = db.query(Company)
    
    # Filter by keyword
    if keyword:
        query = query.filter(
            (Company.ticker.ilike(f"%{keyword}%")) | 
            (Company.name.ilike(f"%{keyword}%"))
        )
    
    companies = query.all()
    results = []
    
    for company in companies:
        # Get latest fundamentals
        latest_fund = db.query(CompanyFundamental).filter(
            CompanyFundamental.ticker == company.ticker
        ).order_by(CompanyFundamental.year.desc()).first()
        
        # Apply financial filters
        if latest_fund:
            if revenue_filter is not None and latest_fund.revenue < revenue_filter:
                continue
            if income_filter is not None and latest_fund.operating_income < income_filter:
                continue
                
            results.append({
                "ticker": company.ticker,
                "name": company.name,
                "year": latest_fund.year,
                "revenue": latest_fund.revenue,
                "operating_income": latest_fund.operating_income,
                "net_income": latest_fund.net_income,
                "eps": latest_fund.eps
            })
        elif revenue_filter is not None or income_filter is not None:
            # Skip if filters are active but no data exists
            continue
        else:
            # No data but no financial filters -> include with placeholders
            results.append({
                "ticker": company.ticker,
                "name": company.name,
                "year": "-",
                "revenue": 0,
                "operating_income": 0,
                "net_income": 0,
                "eps": 0
            })
    
    return templates.TemplateResponse(
        "partials/screener_results.html", 
        {"request": request, "results": results}
    )

@app.post("/admin/sync")
async def manual_sync(request: Request, ticker: str = "7203.T", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    sync_stock_data(db, target_ticker=ticker)
    
    # Re-render page after sync
    return await dashboard(request, ticker=ticker, db=db, current_user=current_user)

# --- Auth Endpoints ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/login")
async def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()

    # ログイン失敗の監査ログ
    if not user or not verify_password(password, user.hashed_password):
        await create_audit_log(
            db=db,
            action_type="LOGIN_FAILED",
            action_category="AUTH",
            request=request,
            details={"username": username, "reason": "Invalid credentials"}
        )
        return RedirectResponse(url="/login?error=ユーザー名またはパスワードが違います", status_code=status.HTTP_303_SEE_OTHER)

    # ログイン成功の監査ログ
    await create_audit_log(
        db=db,
        action_type="LOGIN_SUCCESS",
        action_category="AUTH",
        request=request,
        user=user
    )

    access_token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        return HTMLResponse(content="<p style='color:red;'>このユーザー名はお使いいただけません</p>", status_code=400)

    new_user = User(username=username, hashed_password=get_hashed_password(password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 新規登録の監査ログ
    await create_audit_log(
        db=db,
        action_type="REGISTER",
        action_category="AUTH",
        request=request,
        user=new_user
    )

    return RedirectResponse(url=f"/register/success?username={username}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/register/success", response_class=HTMLResponse)
async def register_success(request: Request, username: str = ""):
    return templates.TemplateResponse("register_success.html", {
        "request": request,
        "username": username
    })

@app.get("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    # 現在のユーザーを取得（オプショナル）
    current_user = await get_current_user_optional(request, db)

    # ログアウトの監査ログ
    if current_user:
        await create_audit_log(
            db=db,
            action_type="LOGOUT",
            action_category="AUTH",
            request=request,
            user=current_user
        )

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response

# --- 管理者機能 ---

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    users = db.query(User).all()
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "users": users,
        "user": current_user
    })

@app.get("/admin/audit-logs", response_class=HTMLResponse)
async def admin_audit_logs_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = 1,
    action_type: Optional[str] = None,
    action_category: Optional[str] = None,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    days: int = 30
):
    """管理者用監査ログ一覧ページ"""
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    # ページネーション設定
    per_page = 50
    offset = (page - 1) * per_page

    # ベースクエリ
    query = db.query(AuditLog)

    # フィルタリング
    if action_type:
        query = query.filter(AuditLog.action_type == action_type)
    if action_category:
        query = query.filter(AuditLog.action_category == action_category)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if ip_address:
        query = query.filter(AuditLog.ip_address.like(f"%{ip_address}%"))

    # 日数フィルタ
    if days > 0:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(AuditLog.created_at >= cutoff_date)

    # 総件数取得
    total_count = query.count()
    total_pages = (total_count + per_page - 1) // per_page

    # データ取得（新しい順）
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(per_page).all()

    # ユニークな値（フィルタ用）
    action_types = db.query(AuditLog.action_type).distinct().all()
    action_categories = db.query(AuditLog.action_category).distinct().all()

    return templates.TemplateResponse("admin_audit_logs.html", {
        "request": request,
        "user": current_user,
        "logs": logs,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "per_page": per_page,
        "action_types": [t[0] for t in action_types],
        "action_categories": [c[0] for c in action_categories],
        "current_filters": {
            "action_type": action_type,
            "action_category": action_category,
            "user_id": user_id,
            "ip_address": ip_address,
            "days": days
        }
    })

@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(request: Request, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="自分自身は削除できません")

    # 削除前に監査ログを記録（削除後はユーザー情報が取得できないため）
    await create_audit_log(
        db=db,
        action_type="USER_DELETE",
        action_category="ADMIN",
        request=request,
        user=current_user,
        target_type="USER",
        target_id=target_user.id,
        target_description=target_user.username,
        details={
            "deleted_user_id": target_user.id,
            "deleted_username": target_user.username,
            "deleted_email": target_user.email,
            "was_admin": target_user.is_admin,
            "was_premium": target_user.is_premium
        }
    )

    db.delete(target_user)
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)

# --- ユーザーアカウント管理 ---

@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Fetch user's comment history
    user_comments = db.query(StockComment).filter(StockComment.user_id == current_user.id).order_by(StockComment.created_at.desc()).all()

    # Get premium tier and usage info
    premium_tier = get_user_tier(current_user)

    # Get usage statistics
    favorites_count = db.query(UserFavorite).filter(UserFavorite.user_id == current_user.id).count()
    favorites_limit = get_feature_limit(current_user, "favorites")

    # AI analyses today
    ai_analyses_today = get_ai_usage_today(db, current_user)
    ai_analyses_limit = get_feature_limit(current_user, "ai_analyses")

    premium_usage = {
        "favorites_count": favorites_count,
        "favorites_limit": favorites_limit,
        "ai_analyses_today": ai_analyses_today,
        "ai_analyses_limit": ai_analyses_limit,
    }

    return templates.TemplateResponse("account.html", {
        "request": request,
        "user": current_user,
        "comments": user_comments,
        "premium_tier": premium_tier,
        "premium_usage": premium_usage
    })

@app.post("/account/delete")
async def delete_own_account(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="ログインが必要です")

    db.delete(current_user)
    db.commit()

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response

# --- Premium Plan Pages ---

@app.get("/premium", response_class=HTMLResponse)
async def premium_page(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    """Premium plan pricing page"""
    current_tier = get_user_tier(current_user)

    return templates.TemplateResponse("premium.html", {
        "request": request,
        "user": current_user,
        "current_tier": current_tier,
        "tier_display_name": get_tier_display_name(current_tier)
    })

@app.get("/technical-chart", response_class=HTMLResponse)
async def technical_chart_demo(
    request: Request,
    ticker: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Technical Analysis Chart Demo Page - Premium Feature Showcase"""
    # Default ticker or from query parameter
    default_ticker = ticker if ticker else "7203"

    return templates.TemplateResponse("technical_chart_demo.html", {
        "request": request,
        "user": current_user,
        "default_ticker": default_ticker
    })

@app.post("/api/test-email")
async def send_test_email(email: str = Form(...), current_user: User = Depends(get_current_user)):
    """Test email sending functionality"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        success = send_email(
            subject="【X-Server App】テストメール",
            recipient=email,
            body="<h1>メール通知のテストです</h1><p>これが届けば設定は成功です！</p>"
        )
        
        if success:
            # Return HTML response for HTMX
            return HTMLResponse(content=f"""
                <div class="alert alert-success">
                    ✅ メールが正常に送信されました！<br>
                    送信先: <strong>{email}</strong>
                </div>
            """)
        else:
            return HTMLResponse(content="""
                <div class="alert alert-error">
                    ❌ メール送信に失敗しました。設定を確認してください。
                </div>
            """, status_code=500)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"""
            <div class="alert alert-error">
                ❌ エラーが発生しました: {str(e)}
            </div>
        """, status_code=500)

@app.get("/api/market/upcoming-earnings")
async def get_upcoming_earnings():
    """
    Get list of companies with upcoming earnings announcements (from DB).
    """
    db = SessionLocal()
    try:
        today = datetime.now().date()
        # Get earnings from today onwards, limit 10
        upcoming = db.query(Company).filter(
            Company.next_earnings_date >= today
        ).order_by(Company.next_earnings_date.asc()).limit(15).all()
        
        if not upcoming:
            return HTMLResponse(content="""
                <div style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1.5rem; text-align: center; color: var(--text-dim);">
                    <p style="margin: 0;">直近の決算予定データはありません</p>
                    <p style="font-size: 0.7rem; margin-top: 0.5rem;">※毎日19:00頃に翌営業日分が更新されます</p>
                </div>
            """)
            
        html = f"""
        <div style="background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: 12px; padding: 1rem;">
            <h3 style="font-family: 'Outfit', sans-serif; font-size: 1.1rem; color: var(--accent); display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem;">
                <span>📢</span>
                <span>直近の決算発表</span>
            </h3>
            <div style="display: flex; flex-direction: column; gap: 0.5rem;">
        """
        
        for company in upcoming:
            delta = (company.next_earnings_date - today).days
            date_str = company.next_earnings_date.strftime("%m/%d")
            
            # Badge color
            if delta == 0:
                badge_bg = "rgba(244, 63, 94, 0.2)"
                badge_color = "#f43f5e"
                delta_text = "今日"
            elif delta == 1:
                badge_bg = "rgba(245, 158, 11, 0.2)"
                badge_color = "#f59e0b"
                delta_text = "明日"
            else:
                badge_bg = "rgba(16, 185, 129, 0.1)"
                badge_color = "#10b981"
                delta_text = f"あと{delta}日"
                
            html += f"""
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.05);">
                <div style="display: flex; flex-direction: column;">
                    <span style="font-weight: 600; font-size: 0.9rem; color: #f8fafc;">{company.name}</span>
                    <span style="font-size: 0.75rem; color: var(--text-dim);">
                        {company.code_4digit} | {date_str}
                    </span>
                </div>
                <span style="background: {badge_bg}; color: {badge_color}; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 999px; font-weight: 600; white-space: nowrap;">
                    {delta_text}
                </span>
            </div>
            """
            
        html += """
            </div>
            <div style="text-align: right; margin-top: 1rem;">
                <span style="font-size: 0.7rem; color: var(--text-dim);">J-Quants Calendar</span>
            </div>
        </div>
        """
        
        return HTMLResponse(content=html)
        
    except Exception as e:
        # Assuming logger is defined elsewhere, otherwise this would be an error
        # import logging
        # logger = logging.getLogger(__name__)
        # logger.error(f"Upcoming earnings error: {e}")
        return HTMLResponse(content=f"<div class='alert alert-error'>Error: {str(e)}</div>", status_code=500)
    finally:
        db.close()


# --- Favorites API Endpoints ---
@app.post("/api/favorites/add")
async def add_favorite(
    request: Request,
    ticker: str = Form(...),
    ticker_name: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a stock to user's favorites with premium tier limit check"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    # Check premium tier limit
    favorites_count = db.query(UserFavorite).filter(UserFavorite.user_id == current_user.id).count()
    favorites_limit = get_feature_limit(current_user, "favorites")

    # Check if already exists (flexible check)
    possible_tickers = [ticker]
    if ticker.endswith(".T"):
        possible_tickers.append(ticker[:-2])
    else:
        possible_tickers.append(f"{ticker}.T")

    existing = db.query(UserFavorite).filter(
        UserFavorite.user_id == current_user.id,
        UserFavorite.ticker.in_(possible_tickers)
    ).first()

    if not existing:
        # Check if user has reached their limit
        if favorites_count >= favorites_limit:
            # Return HTML response with upgrade prompt
            tier = get_user_tier(current_user)
            return HTMLResponse(content=f"""
                <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 12px; padding: 1.5rem; text-align: center;">
                    <h3 style="color: #f59e0b; margin-bottom: 0.5rem;">⭐ お気に入り上限に達しました</h3>
                    <p style="color: #94a3b8; margin-bottom: 1rem;">
                        現在のプラン（{get_tier_display_name(tier)}）では{favorites_limit}銘柄まで登録できます。
                    </p>
                    <a href="/premium" style="display: inline-block; background: linear-gradient(135deg, #f59e0b, #d97706); color: white; padding: 0.75rem 2rem; border-radius: 8px; text-decoration: none; font-weight: 600;">
                        プレミアムプランにアップグレード
                    </a>
                </div>
            """, status_code=200)

        # Add to favorites
        fav = UserFavorite(user_id=current_user.id, ticker=ticker)
        db.add(fav)

        # Also add/update Company record with name if provided
        if ticker_name:
            company = db.query(Company).filter(Company.ticker == ticker).first()
            if not company:
                company = Company(ticker=ticker, name=ticker_name)
                db.add(company)
            elif not company.name:
                company.name = ticker_name

        db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/favorites/remove")
async def remove_favorite(
    request: Request,
    ticker: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a stock from user's favorites"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Remove all variations (flexible remove)
    possible_tickers = [ticker]
    if ticker.endswith(".T"):
        possible_tickers.append(ticker[:-2])
    else:
        possible_tickers.append(f"{ticker}.T")
    
    db.query(UserFavorite).filter(
        UserFavorite.user_id == current_user.id,
        UserFavorite.ticker.in_(possible_tickers)
    ).delete(synchronize_session=False)
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=303)



# --- Discussion Board API Endpoints ---

def render_like_button(comment_id: int, like_count: int, is_liked: bool, user_list: str):
    """いいねボタンのHTML生成"""
    if is_liked:
        # いいね済み - 青色/太字
        button_style = "color: #60a5fa; font-weight: 700; cursor: pointer; font-size: 0.85rem; background: transparent; border: none; padding: 0.3rem 0.6rem; border-radius: 6px; transition: all 0.2s;"
    else:
        # 未いいね - グレー
        button_style = "color: #64748b; font-weight: 400; cursor: pointer; font-size: 0.85rem; background: transparent; border: none; padding: 0.3rem 0.6rem; border-radius: 6px; transition: all 0.2s;"

    title_attr = f'title="{user_list}"' if user_list else ''

    return f"""
        <button
            hx-post="/api/comments/{comment_id}/like"
            hx-target="this"
            hx-swap="outerHTML"
            style="{button_style}"
            {title_attr}
            onmouseover="this.style.background='rgba(96, 165, 250, 0.1)'"
            onmouseout="this.style.background='transparent'">
            👍 {like_count}
        </button>
    """

@app.get("/api/comments/{ticker}", response_class=HTMLResponse)
async def list_comments(
    request: Request,
    ticker: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all comments for a specific ticker and provide a post form"""
    try:
        if not current_user:
            return "<p class='text-gray-400 text-center p-4'>掲示板を表示するにはログインが必要です。</p>"

        comments = db.query(StockComment).filter(StockComment.ticker == ticker).order_by(StockComment.created_at.desc()).all()
    except Exception as e:
        logger.error(f"Error loading comments for {ticker}: {e}")
        import traceback
        traceback.print_exc()
        return f"<p class='text-red-400 text-center p-4'>掲示板の読み込みエラー: {str(e)}</p>"

    # Import html module with alias to avoid name conflict
    import html as html_module

    result_html = f"""
        <div id="discussion-board-{ticker}" style="background: rgba(15, 23, 42, 0.4); border-radius: 16px; border: 1px solid rgba(255,255,255,0.05); padding: 1.5rem;">
            <h3 style="color: #818cf8; font-family: 'Outfit', sans-serif; font-size: 1.1rem; margin-bottom: 1rem; display: flex; align-items: center; justify-content: center; gap: 0.5rem;">
                💬 {ticker} 投資家掲示板
            </h3>
            
            <!-- Post Form -->
            <div style="margin-bottom: 2rem; background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 12px;">
                <form hx-post="/api/comments/{ticker}" hx-target="#comments-list-{ticker}" hx-swap="afterbegin" hx-on::after-request="this.reset()">
                    <textarea name="content" placeholder="この銘柄についての意見や分析を投稿しましょう..." required
                        style="width: 100%; min-height: 80px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 0.75rem; color: #f8fafc; font-size: 0.9rem; resize: vertical; outline: none; margin-bottom: 0.5rem;"></textarea>
                    <div style="text-align: right;">
                        <button type="submit" style="background: linear-gradient(135deg, #6366f1, #8b5cf6); border: none; padding: 0.5rem 1.2rem; border-radius: 8px; color: white; font-weight: 600; cursor: pointer; font-size: 0.85rem;">
                            投稿する
                        </button>
                    </div>
                </form>
            </div>

            <!-- Comments List -->
            <div id="comments-list-{ticker}" style="display: flex; flex-direction: column; gap: 1rem; max-height: 500px; overflow-y: auto; padding-right: 0.5rem;">
    """
    
    if not comments:
        # Initial empty state (will be hidden if a comment is added via JS logic, or just appended to)
        # However, hx-swap="afterbegin" pre-pends. If we leave this message, it stays at bottom. That's fine.
        result_html += f"<p id='no-comments-{ticker}' style='color: #475569; text-align: center; font-size: 0.85rem; padding: 2rem;'>まだ投稿がありません。最初の意見を投稿しましょう！</p>"
    else:
        for comment in comments:
            # Skip comments with deleted users
            if not comment.user:
                continue

            is_owner = comment.user_id == current_user.id
            delete_btn = f"""
                <button hx-delete="/api/comments/{comment.id}" hx-confirm="この投稿を削除しますか？" hx-target="closest .comment-card" hx-swap="outerHTML"
                    style="background: transparent; border: none; color: #f43f5e; cursor: pointer; font-size: 0.75rem; opacity: 0.6; padding: 0;">
                    削除
                </button>
            """ if is_owner else ""

            # Safely get created_at timestamp
            created_at_str = comment.created_at.strftime('%Y-%m-%d %H:%M') if comment.created_at else "Unknown"

            # いいね情報を取得
            like_count = db.query(func.count(CommentLike.id)).filter(
                CommentLike.comment_id == comment.id
            ).scalar() or 0

            is_liked = db.query(CommentLike).filter(
                CommentLike.comment_id == comment.id,
                CommentLike.user_id == current_user.id
            ).first() is not None

            liked_users = db.query(User).join(CommentLike).filter(
                CommentLike.comment_id == comment.id
            ).limit(10).all()

            user_list = ", ".join([f"@{u.username}" for u in liked_users])
            if like_count > 10:
                user_list += f", 他{like_count - 10}名"

            like_button_html = render_like_button(comment.id, like_count, is_liked, user_list)

            result_html += f"""
                <div class="comment-card" style="background: rgba(255,110,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 1rem; position: relative;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                        <a href="/u/{comment.user.username}" style="color: #94a3b8; font-size: 0.8rem; font-weight: 600; text-decoration: none;" onmouseover="this.style.color='#818cf8'" onmouseout="this.style.color='#94a3b8'">@{comment.user.username}</a>
                        <span style="color: #475569; font-size: 0.75rem;">{created_at_str}</span>
                    </div>
                    <div style="color: #f8fafc; font-size: 0.9rem; line-height: 1.5; white-space: pre-wrap;">{html_module.escape(comment.content)}</div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.5rem;">
                        <div>
                            {like_button_html}
                        </div>
                        <div style="text-align: right;">
                            {delete_btn}
                        </div>
                    </div>
                </div>
            """

    result_html += "</div></div>"
    return result_html

@app.post("/api/comments/{ticker}", response_class=HTMLResponse)
async def post_comment(
    ticker: str,
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new comment for a ticker"""
    try:
        if not current_user:
            raise HTTPException(status_code=401)

        if not content.strip():
            return ""

        comment = StockComment(
            user_id=current_user.id,
            ticker=ticker,
            content=content
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)
    except Exception as e:
        logger.error(f"Error posting comment for {ticker}: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return f"<p class='text-red-400 p-2'>投稿エラー: {str(e)}</p>"
    
    # Return JUST the new comment card.
    # HTMX swap="afterbegin" on #comments-list-{ticker} will insert this at the top.
    import html as html_module

    # 新規投稿時はいいね数0
    like_button_html = render_like_button(comment.id, 0, False, "")

    result_html = f"""
        <div class="comment-card" style="background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 12px; padding: 1rem; position: relative; animation: fadeIn 0.5s ease-out;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                <a href="/u/{current_user.username}" style="color: #10b981; font-size: 0.8rem; font-weight: 600; text-decoration: none;" onmouseover="this.style.color='#34d399'" onmouseout="this.style.color='#10b981'">@{current_user.username}</a>
                <span style="color: #475569; font-size: 0.75rem;">Now</span>
            </div>
            <div style="color: #f8fafc; font-size: 0.9rem; line-height: 1.5; white-space: pre-wrap;">{html_module.escape(comment.content)}</div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.5rem;">
                <div>
                    {like_button_html}
                </div>
                <div style="text-align: right;">
                    <button hx-delete="/api/comments/{comment.id}" hx-confirm="この投稿を削除しますか？" hx-target="closest .comment-card" hx-swap="outerHTML"
                        style="background: transparent; border: none; color: #f43f5e; cursor: pointer; font-size: 0.75rem; opacity: 0.6; padding: 0;">
                        削除
                    </button>
                </div>
            </div>
            <script>
                // Hide "no comments" message if exists
                var noCommentMsg = document.getElementById('no-comments-{ticker}');
                if(noCommentMsg) noCommentMsg.style.display = 'none';
            </script>
        </div>
    """
    return result_html

@app.delete("/api/comments/{comment_id}")
async def delete_comment(
    request: Request,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a comment if owner"""
    if not current_user:
        raise HTTPException(status_code=401)

    comment = db.query(StockComment).filter(StockComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404)

    if comment.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403)

    # 削除前に監査ログを記録（削除後はコメント情報が取得できないため）
    is_admin_delete = comment.user_id != current_user.id
    action_type = "COMMENT_DELETE_ADMIN" if is_admin_delete else "COMMENT_DELETE_OWNER"

    # コメント内容のプレビュー（最初の100文字）
    content_preview = comment.content[:100] + "..." if len(comment.content) > 100 else comment.content

    await create_audit_log(
        db=db,
        action_type=action_type,
        action_category="MODERATION",
        request=request,
        user=current_user,
        target_type="COMMENT",
        target_id=comment.id,
        target_description=f"投稿 by {comment.user.username if comment.user else 'Unknown'}",
        details={
            "comment_id": comment.id,
            "comment_ticker": comment.ticker,
            "comment_author_id": comment.user_id,
            "comment_author": comment.user.username if comment.user else None,
            "content_preview": content_preview,
            "deleted_by_admin": is_admin_delete
        }
    )

    db.delete(comment)
    db.commit()
    return Response(status_code=status.HTTP_200_OK)

@app.post("/api/comments/{comment_id}/like", response_class=HTMLResponse)
async def toggle_comment_like(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """コメントのいいねを追加/削除（トグル）"""
    if not current_user:
        return HTMLResponse(content="<p style='color:#f43f5e;'>ログインが必要です</p>", status_code=401)

    # コメントの存在確認
    comment = db.query(StockComment).filter(StockComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")

    # 既存のいいねをチェック
    existing_like = db.query(CommentLike).filter(
        CommentLike.comment_id == comment_id,
        CommentLike.user_id == current_user.id
    ).first()

    if existing_like:
        # いいね解除
        db.delete(existing_like)
        db.commit()
        is_liked = False
    else:
        # いいね追加
        new_like = CommentLike(comment_id=comment_id, user_id=current_user.id)
        db.add(new_like)
        db.commit()
        is_liked = True

    # いいね数とユーザー一覧を再計算
    like_count = db.query(func.count(CommentLike.id)).filter(
        CommentLike.comment_id == comment_id
    ).scalar() or 0

    # いいねしたユーザー一覧を取得（最大10名）
    liked_users = db.query(User).join(CommentLike).filter(
        CommentLike.comment_id == comment_id
    ).limit(10).all()

    user_list = ", ".join([f"@{u.username}" for u in liked_users])
    if like_count > 10:
        user_list += f", 他{like_count - 10}名"

    return render_like_button(comment_id, like_count, is_liked, user_list)


@app.get("/api/companies/search", response_class=HTMLResponse)
async def search_companies(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Search companies by ticker or name and return HTML list items for HTMX.
    """
    if not q:
        return ""

    # Search logic: ticker starts with query OR name contains query
    # Using specific 4-digit code matching if query is digits
    if q.isdigit():
        companies = db.query(Company).filter(
            or_(
                Company.ticker.startswith(q),
                Company.code_4digit.startswith(q)
            )
        ).limit(10).all()
    else:
        companies = db.query(Company).filter(
            Company.name.ilike(f"%{q}%")
        ).limit(10).all()

    if not companies:
        return "<li style='padding: 0.75rem; font-size: 0.85rem; color: #64748b; text-align: center;'>該当なし</li>"

    html_content = ""
    for company in companies:
        # Extract 4-digit code for cleaner display
        code = company.code_4digit if company.code_4digit else company.ticker.split('.')[0]
        
        # Create list item with better mobile touch handling
        # Escape company name for JavaScript
        company_name_escaped = company.name.replace("'", "\\'").replace('"', '\\"')

        # Use mousedown instead of click to fire before blur event
        click_handler = f"debugLog('👆 Item clicked: {code}', 'success'); document.getElementById('yf-ticker-input').value = '{code}'; document.getElementById('yf-company-name').value = '{company_name_escaped}'; var list = document.getElementById('company-search-results'); list.style.display = 'none'; setTimeout(function(){{list.innerHTML = '';}}, 100); return false;"

        html_content += f"""
        <li style="padding: 0.75rem 1rem; cursor: pointer; font-size: 0.9rem; color: #e2e8f0; border-bottom: 1px solid rgba(255, 255, 255, 0.08); transition: background 0.2s; user-select: none; -webkit-tap-highlight-color: rgba(255, 255, 255, 0.1);"
            onmouseover="this.style.background='rgba(255, 255, 255, 0.1)';"
            onmouseout="this.style.background='transparent';"
            onmousedown="{click_handler}"
            ontouchstart="{click_handler}">
            <span style="font-weight: bold; color: #10b981; margin-right: 0.5rem;">{code}</span>
            <span>{company_name_escaped}</span>
        </li>
        """
    
    return html_content


@app.get("/api/companies/get-name")
async def get_company_name(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Get company name by ticker or 4-digit code.
    Returns JSON with name or empty string if not found.
    """
    if not q:
        return {"name": ""}

    # Exact match or prefix match logic
    # Prioritize exact match on code_4digit or ticker
    company = db.query(Company).filter(
        or_(
            Company.code_4digit == q,
            Company.ticker == q,
            Company.ticker == f"{q}.T"
        )
    ).first()

    if company:
        return {"name": company.name}
    
    return {"name": ""}



@app.post("/api/yahoo-finance/lookup")
async def lookup_yahoo_finance(
    background_tasks: BackgroundTasks,
    ticker_code: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lookup any stock by code using Yahoo Finance API"""
    if not current_user:
        return HTMLResponse(content="<div class='text-red-400 p-4'>ログインが必要です</div>")
    
    # Clean the ticker code
    code_input = ticker_code.strip()
    if not code_input:
        return HTMLResponse(content="<div class='text-yellow-400 p-4'>銘柄コードを入力してください</div>")
    
    # For Japanese stocks, append .T for Tokyo Stock Exchange
    if code_input.isdigit() and len(code_input) == 4:
        symbol = f"{code_input}.T"
        # Trigger background EDINET fetch for Japanese stocks
        background_tasks.add_task(fetch_edinet_background, code_input)
    else:
        symbol = code_input
        
    # Ensure code_only is available for templates (e.g. News API, AI Analysis)
    code_only = symbol.replace(".T", "")
    
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Check if valid
        if not info or info.get("regularMarketPrice") is None:
            return HTMLResponse(content=f"""
                <div style="color: #fb7185; padding: 1rem; text-align: center; background: rgba(244, 63, 94, 0.1); border-radius: 8px;">
                    ❌ 銘柄コード「{symbol}」のデータが見つかりませんでした。<br>
                    4桁の証券コード（例: 7203）を入力してください。
                </div>
            """)
            
        # Extract key data
        name = info.get("longName") or info.get("shortName") or symbol
        price = info.get("regularMarketPrice", 0)
        prev_close = info.get("previousClose", 0)
        change = price - prev_close if price and prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        
        market_cap = info.get("marketCap", 0)
        market_cap_str = f"{market_cap / 1e12:.2f}兆円" if market_cap > 1e12 else f"{market_cap / 1e8:.0f}億円" if market_cap else "-"
        
        per = info.get("trailingPE") or info.get("forwardPE") or "-"
        pbr = info.get("priceToBook") or "-"
        
        # Extract corporate website URL
        website = info.get("website")
        
        # 配当利回りの取得と計算
        dividend_yield = None
        
        # yfinance の dividendYield は小数形式 (0.0217 = 2.17%)
        yf_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
        
        if yf_yield is not None and yf_yield > 0:
            # yfinance usually returns decimal (0.0217 = 2.17%) -> *100 = 2.17
            dividend_yield = yf_yield * 100
        else:
            # Fallback: Calculate manually
            if price and price > 0:
                div_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
                if div_rate and div_rate > 0:
                    dividend_yield = (div_rate / price) * 100
        
        # [HEURISTIC FIX]
        # Calculate yield is abnormally high (e.g. > 20%), it's likely a scaling issue.
        # User reported 0.62% showing as 62.000%, implying input was 0.62.
        # If yield > 20%, we assume it should be divided by 100.
        if dividend_yield is not None and dividend_yield > 20.0:
            dividend_yield /= 100.0

        dividend_str = f"{dividend_yield:.2f}%" if dividend_yield is not None else "-"
        
        roe = info.get("returnOnEquity")
        roe_str = f"{roe * 100:.1f}%" if roe else "-"
        
        # Color for price change
        change_color = "#10b981" if change >= 0 else "#f43f5e"
        change_sign = "+" if change >= 0 else ""
        
        # Extract Analyst Target Price
        target_mean_price = info.get("targetMeanPrice")
        target_price_html = ""
        if target_mean_price:
            target_price_html = f"<div style='font-size: 0.85rem; color: #94a3b8; font-weight: normal; margin-top: 0.35rem;'>目標株価平均 {target_mean_price:,.0f}円</div>"
        
        # Check if favorite (Check both with and without .T to be safe)
        possible_tickers = [symbol]
        if symbol.endswith(".T"):
            possible_tickers.append(symbol[:-2]) # Add code without .T
        
        is_favorite = db.query(UserFavorite).filter(
            UserFavorite.user_id == current_user.id,
            UserFavorite.ticker.in_(possible_tickers)
        ).first() is not None
        
        if is_favorite:
            fav_button = f"""
                <form action="/api/favorites/remove" method="post" style="margin: 0;">
                    <input type="hidden" name="ticker" value="{symbol}">
                    <button type="submit"
                        style="background: rgba(244, 63, 94, 0.2); border: 1px solid #f43f5e; color: #f43f5e; padding: 0.5rem 1rem; border-radius: 8px; cursor: pointer; font-size: 0.85rem; white-space: nowrap;">
                        ★ 解除
                    </button>
                </form>
            """
        else:
            fav_button = f"""
                <form action="/api/favorites/add" method="post" style="margin: 0;">
                    <input type="hidden" name="ticker" value="{symbol}">
                    <input type="hidden" name="ticker_name" value="{name}">
                    <button type="submit"
                        style="background: rgba(251, 191, 36, 0.2); border: 1px solid #fbbf24; color: #fbbf24; padding: 0.5rem 1rem; border-radius: 8px; cursor: pointer; font-size: 0.85rem; white-space: nowrap;">
                        ☆ 登録
                    </button>
                </form>
            """
        
        # -------------------------------------------------------------------------
        # Fetch Financial Data from Yahoo Finance & Generate Charts
        # -------------------------------------------------------------------------
        import time
        
        # Get financial statements from yfinance
        fin = ticker.financials
        cf = ticker.cashflow
        bs = ticker.balance_sheet
        
        # Prepare data arrays
        years_label = []
        revenue_data = []
        op_income_data = []
        op_margin_data = []
        eps_data = []
        op_cf_data = []
        inv_cf_data = []
        fin_cf_data = []
        net_cf_data = []
        fcf_data = []  # Free Cash Flow
        debt_data = [] # Interest-bearing Debt
        roe_data = []
        roa_data = []
        table_rows = ""
        
        # Helper function to safely get DataFrame values
        def get_val(df, key, date_col):
            try:
                if not df.empty and key in df.index:
                    val = df.loc[key, date_col]
                    return float(val) if pd.notna(val) else 0
            except:
                pass
            return 0
        
        # Convert to billions (億円)
        to_oku = lambda x: round(x / 100000000, 1) if x else 0
        
        # Process data if available
        if not fin.empty:
            dates = sorted(fin.columns, reverse=False)[-4:]  # Last 4 years
            
            for date in dates:
                year = date.strftime("%Y") if hasattr(date, 'strftime') else str(date)[:4]
                years_label.append(year)
                
                # Revenue & Profit
                revenue = get_val(fin, "Total Revenue", date)
                op_income = get_val(fin, "Operating Income", date)
                net_income = get_val(fin, "Net Income", date)
                eps = get_val(fin, "Basic EPS", date)
                
                revenue_data.append(to_oku(revenue))
                op_income_data.append(to_oku(op_income))
                
                # Operating Margin %
                margin = round((op_income / revenue) * 100, 1) if revenue > 0 else 0
                op_margin_data.append(margin)
                eps_data.append(round(eps, 1) if eps else 0)
                
                # Balance Sheet Items (Debt, Equity, Assets)
                total_assets = get_val(bs, "Total Assets", date)
                total_equity = get_val(bs, "Stockholders Equity", date) or get_val(bs, "Total Stockholder Equity", date)
                
                # Debt extraction (Try Total Debt, fallback to Long + Short)
                total_debt = get_val(bs, "Total Debt", date)
                if total_debt == 0:
                     lt_debt = get_val(bs, "Long Term Debt", date)
                     st_debt = get_val(bs, "Current Debt", date) or get_val(bs, "Short Long Term Debt", date)
                     total_debt = lt_debt + st_debt

                # Cash Flow
                op_cf = get_val(cf, "Operating Cash Flow", date) or get_val(cf, "Total Cash From Operating Activities", date)
                inv_cf = get_val(cf, "Investing Cash Flow", date) or get_val(cf, "Total Cashflows From Investing Activities", date)
                fin_cf_val = get_val(cf, "Financing Cash Flow", date) or get_val(cf, "Total Cash From Financing Activities", date)
                
                # Free Cash Flow = Operating CF + Investing CF (Investing is usually negative)
                free_cf = op_cf + inv_cf
                
                # ROE / ROA
                roe = (net_income / total_equity * 100) if total_equity else 0
                roa = (net_income / total_assets * 100) if total_assets else 0
                
                op_cf_data.append(to_oku(op_cf))
                inv_cf_data.append(to_oku(inv_cf))
                fin_cf_data.append(to_oku(fin_cf_val))
                net_cf_data.append(to_oku(op_cf + inv_cf + fin_cf_val))
                fcf_data.append(to_oku(free_cf))
                debt_data.append(to_oku(total_debt))
                roe_data.append(round(roe, 1))
                roa_data.append(round(roa, 1))
                
                # Table row
                fmt = lambda x: f"{to_oku(x):,.1f}" if x else "-"
                table_rows += f"""
                    <tr>
                        <td>{year}</td>
                        <td>{fmt(revenue)}</td>
                        <td>{fmt(op_income)}</td>
                        <td>{fmt(net_income)}</td>
                        <td>{round(eps, 1) if eps else '-'}</td>
                        <td>{fmt(op_cf)}</td>
                    </tr>
                """
        
        # -------------------------------------------------------------------------
        # Growth & Quality Analysis
        # -------------------------------------------------------------------------
        growth_analysis = analyze_growth_quality(ticker)
        
        # Prepare growth chart data (10% target)
        growth_labels = []
        growth_rev_actual = []
        growth_rev_target = []
        
        if growth_analysis["history"]:
            # Use up to 5 years for the growth comparison
            hist = growth_analysis["history"][-5:]
            if len(hist) > 0:
                start_rev = hist[0]["revenue"]
                for i, h in enumerate(hist):
                    growth_labels.append(h["date"][:4])
                    growth_rev_actual.append(to_oku(h["revenue"]))
                    # Target line: Start revenue * (1.10 ^ years)
                    target = start_rev * (1.10 ** i)
                    growth_rev_target.append(to_oku(target))

        # Sanitize lists for JSON dump (replace NaN with None/null)
        def clean_list(lst):
            return [x if pd.notna(x) else None for x in lst]
        
        years_label_js = json.dumps(years_label)
        revenue_data_js = json.dumps(clean_list(revenue_data))
        op_income_data_js = json.dumps(clean_list(op_income_data))
        op_margin_data_js = json.dumps(clean_list(op_margin_data))
        op_cf_data_js = json.dumps(clean_list(op_cf_data))
        inv_cf_data_js = json.dumps(clean_list(inv_cf_data))
        fin_cf_data_js = json.dumps(clean_list(fin_cf_data))
        net_cf_data_js = json.dumps(clean_list(net_cf_data))
        fcf_data_js = json.dumps(clean_list(fcf_data))
        debt_data_js = json.dumps(clean_list(debt_data))
        roe_data_js = json.dumps(clean_list(roe_data))
        roa_data_js = json.dumps(clean_list(roa_data))
        growth_labels_js = json.dumps(growth_labels)
        growth_rev_actual_js = json.dumps(clean_list(growth_rev_actual))
        growth_rev_target_js = json.dumps(clean_list(growth_rev_target))

        # Generate unique chart IDs
        chart_id1 = f"perf_{code_input}_{int(time.time())}"
        chart_id2 = f"cf_{code_input}_{int(time.time())}"
        chart_id3 = f"growth_{code_input}_{int(time.time())}"
        chart_id4 = f"fin_health_{code_input}_{int(time.time())}"
        
        # J-Quants Data Lookup
        code_str = symbol.replace(".T", "")
        # Check DB for accurate Japanese name & sector
        company_data = db.query(Company).filter(Company.code_4digit == code_str).first()
        
        sector_html = ""
        edinet_name = name # Default to what we have
        
        if company_data:
            name = company_data.name # Override with official Japanese name
            edinet_name = company_data.name
            if company_data.sector_17:
                sector_html = f"""
                <div style="margin-top: 0.5rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
                    <span style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: #cbd5e1; font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 999px;">
                        {company_data.sector_17}
                    </span>
                    <span style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: #cbd5e1; font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 999px;">
                        {company_data.sector_33}
                    </span>
                </div>
                """

        # Earnings Info Section Logic
        earnings_html = ""
        if company_data and company_data.next_earnings_date:
             earnings_date = company_data.next_earnings_date
             earnings_date_str = earnings_date.strftime("%Y年%m月%d日")
             
             # Calculate days until
             today = datetime.now().date()
             delta = (earnings_date - today).days
             
             badge_color = "#64748b" # gray
             days_until_str = "発表済み"
             
             if delta < 0:
                 days_until_str = "発表済み"
                 badge_color = "#64748b" # gray
             elif delta == 0:
                 days_until_str = "今日発表！"
                 badge_color = "#f43f5e" # red
             elif delta <= 7:
                 days_until_str = f"あと{delta}日"
                 badge_color = "#f43f5e" # red
             elif delta <= 30:
                 days_until_str = f"あと{delta}日"
                 badge_color = "#f59e0b" # amber
             else:
                 days_until_str = f"あと{delta}日"
                 badge_color = "#10b981" # green
                 
             earnings_html = f"""
                <div style="margin-top: 1rem; background: rgba(0,0,0,0.2); border-radius: 8px; padding: 0.75rem; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-size: 1.2rem;">📅</span>
                        <div>
                            <div style="font-size: 0.8rem; color: var(--text-dim);">次回決算発表</div>
                            <div style="font-weight: 600; color: #f8fafc;">{earnings_date_str}</div>
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <span style="background: {badge_color}; color: white; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.8rem; font-weight: 600;">
                            {days_until_str}
                        </span>
                    </div>
                </div>
             """

        # Prepare Header Name HTML (Link to website if available)
        header_name_html = name
        if website:
            header_name_html = f'<a href="{website}" target="_blank" style="color: inherit; text-decoration: none; border-bottom: 1px dotted rgba(255,255,255,0.5); transition: all 0.2s;" onmouseover="this.style.color=\'#818cf8\'; this.style.borderColor=\'#818cf8\'" onmouseout="this.style.color=\'inherit\'; this.style.borderColor=\'rgba(255,255,255,0.5)\'">{name} <span style="font-size: 1rem; vertical-align: middle; opacity: 0.7; margin-left: 0.2rem;">🔗</span></a>'

        # Build clean HTML response with cookie to remember last ticker
        html_content = f"""
            <!-- Stock Info Card -->
            <div style="background: linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.1)); border: 1px solid rgba(99,102,241,0.3); border-radius: 16px; padding: 1.5rem; margin-bottom: 1rem;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem;">
                    <div>
                        <h3 style="font-size: 1.4rem; font-weight: 700; color: #f8fafc; margin: 0;">
                            {header_name_html}
                        </h3>
                        <p style="color: #94a3b8; font-size: 0.9rem; margin: 0.25rem 0 0 0;">{symbol}</p>
                        {sector_html}
                    </div>
                    <div style="text-align: right;">
                        <div class="price-container" style="display: flex; align-items: baseline; justify-content: flex-end; gap: 1.5rem;">
                            {f'<div class="price-item"><span style="font-size: 0.9rem; color: #64748b; margin-right: 0.3rem;">目標株価</span><span style="font-size: 2rem; font-weight: 700; color: #fbbf24;">¥{target_mean_price:,.0f}</span></div>' if target_mean_price else ''}
                            <div class="price-item"><span style="font-size: 0.9rem; color: #64748b; margin-right: 0.3rem;">株価</span><span style="font-size: 2rem; font-weight: 700; color: #f8fafc;">¥{price:,.0f}</span></div>
                        </div>
                        <div style="color: {change_color}; font-size: 1rem; font-weight: 600; margin-top: 0.3rem;">
                            {change_sign}{change:,.0f} ({change_sign}{change_pct:.2f}%)
                        </div>
                        <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                            <a href="/technical-chart?ticker={code_only}"
                               style="display: inline-flex; align-items: center; gap: 0.3rem; background: linear-gradient(135deg, #a855f7 0%, #9333ea 100%); color: white; text-decoration: none; padding: 0.4rem 0.8rem; border-radius: 8px; font-size: 0.8rem; font-weight: 600; box-shadow: 0 2px 4px rgba(168, 85, 247, 0.2);">
                               <span>📈</span> テクニカルチャート
                            </a>
                            <a href="/edinet?code={code_str}&company_name={edinet_name}"
                               style="display: inline-flex; align-items: center; gap: 0.3rem; background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; text-decoration: none; padding: 0.4rem 0.8rem; border-radius: 8px; font-size: 0.8rem; font-weight: 600; box-shadow: 0 2px 4px rgba(16, 185, 129, 0.2);">
                               <span>📄</span> EDINETで分析
                            </a>
                        </div>
                    </div>
                </div>
                
                {earnings_html}
                
                <!-- Key Metrics Grid with Responsive CSS -->
                <style>
                    .metrics-grid {{ 
                        display: grid; 
                        grid-template-columns: repeat(5, 1fr); 
                        gap: 0.75rem; 
                        margin-top: 1.25rem; 
                    }}
                    .metrics-item {{
                        background: rgba(0,0,0,0.2);
                        padding: 0.75rem;
                        border-radius: 10px;
                        text-align: center;
                    }}
                    .metrics-label {{
                        color: #64748b;
                        font-size: 0.75rem;
                        margin-bottom: 0.2rem;
                    }}
                    .metrics-value {{
                        font-weight: 600;
                        font-size: 1rem;
                    }}
                    @media (max-width: 600px) {{
                        .metrics-grid {{
                            grid-template-columns: repeat(3, 1fr);
                            gap: 0.5rem;
                        }}
                        .metrics-item {{
                            padding: 0.5rem;
                        }}
                        .metrics-label {{
                            font-size: 0.65rem;
                        }}
                        .metrics-value {{
                            font-size: 0.85rem;
                        }}
                        .price-container {{
                            flex-direction: column !important;
                            gap: 0.5rem !important;
                            align-items: flex-end !important;
                        }}
                        .price-item span:first-child {{
                            font-size: 0.7rem !important;
                        }}
                        .price-item span:last-child {{
                            font-size: 1.4rem !important;
                        }}
                    }}
                </style>
                <div class="metrics-grid">
                    <div class="metrics-item">
                        <div class="metrics-label">時価総額</div>
                        <div class="metrics-value" style="color: #f8fafc;">{market_cap_str}</div>
                    </div>
                    <div class="metrics-item">
                        <div class="metrics-label">PER</div>
                        <div class="metrics-value" style="color: #f8fafc;">{per if isinstance(per, str) else f'{per:.1f}'}</div>
                    </div>
                    <div class="metrics-item">
                        <div class="metrics-label">PBR</div>
                        <div class="metrics-value" style="color: #f8fafc;">{pbr if isinstance(pbr, str) else f'{pbr:.2f}'}</div>
                    </div>
                    <div class="metrics-item">
                        <div class="metrics-label">配当利回り</div>
                        <div class="metrics-value" style="color: #10b981;">{dividend_str}</div>
                    </div>
                    <div class="metrics-item">
                        <div class="metrics-label">ROE</div>
                        <div class="metrics-value" style="color: #818cf8;">{roe_str}</div>
                    </div>
                </div>
                
                <!-- Share Buttons -->
                <div style="display: flex; justify-content: flex-end; align-items: center; margin-top: 1rem; gap: 0.5rem;">
                    <a href="https://twitter.com/intent/tweet?text={name}%20({symbol})%20%C2%A5{int(price):,}%20%23株式分析&url=https://site.y-project-vps.xyz/&hashtags=XStockAnalyzer" target="_blank" 
                        style="background: rgba(29, 161, 242, 0.15); border: 1px solid rgba(29, 161, 242, 0.4); color: #1DA1F2; text-decoration: none; padding: 0.5rem 0.75rem; border-radius: 8px; font-size: 0.8rem; display: flex; align-items: center; gap: 0.4rem;">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"></path></svg>
                        Xでシェア
                    </a>
                    <button onclick="navigator.clipboard.writeText('https://site.y-project-vps.xyz/').then(() => {{ this.innerHTML = '✅ コピー!'; setTimeout(() => this.innerHTML = '🔗 URLコピー', 2000); }})"
                        style="background: rgba(148, 163, 184, 0.15); border: 1px solid rgba(148, 163, 184, 0.4); color: #94a3b8; padding: 0.5rem 0.75rem; border-radius: 8px; cursor: pointer; font-size: 0.8rem;">
                        🔗 URLコピー
                    </button>
                </div>


            </div>

            <!-- Charts Section (OOB Swap) -->
            <div id="chart-section" class="section" hx-swap-oob="true">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                    <h2 style="font-family: 'Outfit', sans-serif; font-size: 1.2rem; margin: 0; color: #818cf8;">
                        📊 財務パフォーマンス
                    </h2>
                    <div style="display: flex; gap: 0.5rem;">
                        <button id="capture-dashboard-btn" onclick="captureDashboard()" 
                            style="background: rgba(99, 102, 241, 0.2); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.4); padding: 0.4rem 0.6rem; border-radius: 8px; cursor: pointer; font-size: 0.7rem; display: flex; align-items: center; gap: 0.3rem; transition: all 0.2s;">
                            📋 コピー
                        </button>
                        <button id="visual-analyze-btn" onclick="visualAnalyzeDashboard()" 
                            style="background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 8px; cursor: pointer; font-size: 0.7rem; display: flex; align-items: center; gap: 0.3rem; transition: all 0.2s; font-weight: 500;">
                            🤖 AI画像診断
                        </button>
                    </div>
                </div>
                
                <!-- Visual Analysis Result Container -->
                <div id="visual-analysis-result" style="display: none; margin-bottom: 1rem; padding: 1rem; background: rgba(15, 23, 42, 0.95); border-radius: 12px; border: 1px solid rgba(99, 102, 241, 0.4);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; padding-bottom: 0.5rem; border-bottom: 1px solid rgba(99, 102, 241, 0.2);">
                        <h4 style="margin: 0; color: #a5b4fc; font-size: 0.95rem; font-weight: 600;">🤖 AI画像診断レポート</h4>
                        <button onclick="document.getElementById('visual-analysis-result').style.display='none'" 
                            style="background: rgba(239, 68, 68, 0.2); border: none; color: #fb7185; cursor: pointer; font-size: 0.8rem; padding: 0.25rem 0.5rem; border-radius: 4px;">✕ 閉じる</button>
                    </div>
                    
                    <!-- markedライブラリの読み込み（ローカル） -->
                    <script src="/static/marked.min.js"></script>
                    
                    <style>
                        /* スクロール可能なコンテンツエリア */
                        #visual-analysis-content {{
                            max-height: 500px;
                            overflow-y: auto;
                            padding-right: 0.5rem;
                            color: #e2e8f0; 
                            font-size: 0.95rem; 
                            line-height: 1.8;
                        }}
                        
                        /* Markdown スタイル */
                        #visual-analysis-content h1, 
                        #visual-analysis-content h2, 
                        #visual-analysis-content h3 {{ 
                            color: #a5b4fc; 
                            margin-top: 1.5rem; 
                            margin-bottom: 0.75rem; 
                            font-weight: 700; 
                        }}
                        #visual-analysis-content h1 {{ font-size: 1.5rem; border-bottom: 1px solid rgba(99, 102, 241, 0.4); padding-bottom: 0.5rem; }}
                        #visual-analysis-content h2 {{ font-size: 1.25rem; }}
                        #visual-analysis-content h3 {{ font-size: 1.15rem; }}
                        #visual-analysis-content p {{ margin-bottom: 1.2rem; }}
                        #visual-analysis-content ul, #visual-analysis-content ol {{ padding-left: 1.5rem; margin-bottom: 1.2rem; }}
                        #visual-analysis-content li {{ margin-bottom: 0.6rem; }}
                        #visual-analysis-content strong {{ color: #fbbf24; font-weight: 700; }}
                        
                        /* テーブルスタイル */
                        #visual-analysis-content table {{ 
                            width: 100%; 
                            border-collapse: collapse; 
                            margin: 1.5rem 0; 
                            font-size: 0.9rem; 
                            background: rgba(30, 41, 59, 0.4); 
                        }}
                        #visual-analysis-content th {{ 
                            background: rgba(99, 102, 241, 0.25); 
                            color: #c7d2fe; 
                            padding: 0.8rem; 
                            border: 1px solid rgba(71, 85, 105, 0.6); 
                            text-align: left; 
                        }}
                        #visual-analysis-content td {{ 
                            padding: 0.8rem; 
                            border: 1px solid rgba(71, 85, 105, 0.6); 
                            color: #e2e8f0; 
                        }}
                        #visual-analysis-content blockquote {{ 
                            border-left: 4px solid #6366f1; 
                            padding-left: 1rem; 
                            color: #94a3b8; 
                            margin: 1.5rem 0; 
                            font-style: italic; 
                            background: rgba(99, 102, 241, 0.05); 
                            padding: 0.5rem 1rem; 
                            border-radius: 0 8px 8px 0; 
                        }}
                        
                        /* カスタムスクロールバー */
                        #visual-analysis-content::-webkit-scrollbar {{ width: 8px; }}
                        #visual-analysis-content::-webkit-scrollbar-track {{ background: rgba(15, 23, 42, 0.6); border-radius: 4px; }}
                        #visual-analysis-content::-webkit-scrollbar-thumb {{ background: #6366f1; border-radius: 4px; }}
                        #visual-analysis-content::-webkit-scrollbar-thumb:hover {{ background: #818cf8; }}
                    </style>
                    
                    <div id="visual-analysis-content"></div>
                </div>
                
                <script>
                // Clipboard copy function
                async function captureDashboard() {{
                    console.log('Capture started');
                    const btn = document.getElementById('capture-dashboard-btn');
                    const originalText = btn.innerHTML;
                    
                    try {{
                        btn.disabled = true;
                        btn.innerHTML = '⏳';
                        
                        if (typeof html2canvas === 'undefined') {{
                            alert('画像化ライブラリが読み込まれていません。');
                            throw new Error('html2canvas not loaded');
                        }}
                        
                        const chartSection = document.getElementById('charts-only');
                        if (!chartSection) {{
                            throw new Error('Chart section not found');
                        }}
                        
                        const canvas = await html2canvas(chartSection, {{
                            backgroundColor: '#0f172a',
                            scale: 1.5,
                            useCORS: true,
                            allowTaint: false,
                            logging: false,
                            willReadFrequently: true,
                            onclone: (clonedDoc) => {{
                                const el = clonedDoc.getElementById('charts-only');
                                if (el) {{
                                    el.style.width = chartSection.offsetWidth + 'px';
                                    el.style.display = 'flex';
                                }}
                                // Set willReadFrequently for all canvas elements to suppress warnings
                                const canvases = clonedDoc.getElementsByTagName('canvas');
                                for (let i = 0; i < canvases.length; i++) {{
                                    const ctx = canvases[i].getContext('2d', {{ willReadFrequently: true }});
                                }}
                            }}
                        }});
                        
                        canvas.toBlob(async function(blob) {{
                            if (!blob) return;
                            try {{
                                // Check for ClipboardItem support
                                if (typeof ClipboardItem !== 'undefined' && navigator.clipboard && navigator.clipboard.write) {{
                                    const clipboardItem = new ClipboardItem({{ 'image/png': blob }});
                                    await navigator.clipboard.write([clipboardItem]);
                                    btn.innerHTML = '✅';
                                    setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 1500);
                                }} else {{
                                    throw new Error('ClipboardItem not supported');
                                }}
                            }} catch (e) {{
                                console.log('Falling back to download due to:', e.message);
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = 'dashboard.png';
                                document.body.appendChild(a);
                                a.click();
                                document.body.removeChild(a);
                                URL.revokeObjectURL(url);
                                btn.innerHTML = '📥';
                                setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 1500);
                            }}
                        }}, 'image/png');
                        
                    }} catch (error) {{
                        console.error('Capture failed:', error);
                        btn.innerHTML = '❌';
                        alert('コピーに失敗しました: ' + error.message);
                        setTimeout(() => {{ btn.innerHTML = originalText; btn.disabled = false; }}, 2000);
                    }}
                }}
                window.captureDashboard = captureDashboard;
                
                // AI Visual Analysis function (Phase 1: HTML direct response)
                async function visualAnalyzeDashboard() {{
                    console.log('AI Visual analysis started');
                    const btn = document.getElementById('visual-analyze-btn');
                    const resultContainer = document.getElementById('visual-analysis-result');
                    const resultContent = document.getElementById('visual-analysis-content');
                    if (!btn || !resultContainer || !resultContent) return;

                    const originalText = btn.innerHTML;

                    try {{
                        btn.disabled = true;
                        btn.innerHTML = '⏳ 分析中...';
                        btn.style.opacity = '0.7';
                        resultContainer.style.display = 'block';
                        resultContent.innerHTML = '<div style="text-align: center; padding: 2rem;"><p style="color: #94a3b8;">🤖 AIがグラフを分析中...</p></div>';

                        if (typeof html2canvas === 'undefined') {{
                            throw new Error('html2canvas not loaded');
                        }}

                        const chartSection = document.getElementById('charts-only');
                        if (!chartSection) throw new Error('Chart section not found');

                        const canvas = await html2canvas(chartSection, {{
                            backgroundColor: '#0f172a',
                            scale: 1.2,
                            useCORS: true,
                            logging: false,
                            willReadFrequently: true,
                            onclone: (clonedDoc) => {{
                                // Set willReadFrequently for all canvas elements to suppress warnings
                                const canvases = clonedDoc.getElementsByTagName('canvas');
                                for (let i = 0; i < canvases.length; i++) {{
                                    const ctx = canvases[i].getContext('2d', {{ willReadFrequently: true }});
                                }}
                            }}
                        }});

                        const imageData = canvas.toDataURL('image/png');
                        const tickerCode = '{code_only}';
                        const h3 = document.querySelector('h3');
                        const companyName = h3 ? h3.innerText : '';

                        const formData = new FormData();
                        formData.append('image_data', imageData);
                        formData.append('ticker_code', tickerCode);
                        formData.append('company_name', companyName);

                        const response = await fetch('/api/ai/visual-analyze', {{
                            method: 'POST',
                            body: formData
                        }});

                        if (!response.ok) {{
                            const errorText = await response.text();
                            throw new Error(errorText || 'API request failed');
                        }}

                        // Phase 1: Receive HTML directly from server
                        const html = await response.text();

                        // Check if response is error HTML
                        if (html.includes("class='error'") || html.includes('style=\\'color: #fb7185;\\'')) {{
                            throw new Error(html.replace(/<[^>]*>/g, '')); // Strip HTML tags for error message
                        }}

                        // Directly insert server-rendered HTML
                        resultContent.innerHTML = html;
                        console.log('HTML analysis result rendered successfully');

                        btn.innerHTML = '✅ 完了';
                        btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';

                        setTimeout(function() {{
                            btn.innerHTML = originalText;
                            btn.style.background = 'linear-gradient(135deg, #6366f1, #8b5cf6)';
                            btn.disabled = false;
                            btn.style.opacity = '1';
                        }}, 2000);

                    }} catch (error) {{
                        console.error('Error in visualAnalyzeDashboard:', error);
                        resultContent.innerHTML = '<p style="color:#fb7185; padding: 1rem; border: 1px solid rgba(251,113,133,0.3); border-radius: 8px;">❌ エラー: ' + error.message + '</p>';
                        btn.innerHTML = '❌ エラー';
                        btn.style.background = 'linear-gradient(135deg, #ef4444, #dc2626)';
                        setTimeout(function() {{
                            btn.innerHTML = originalText;
                            btn.style.background = 'linear-gradient(135deg, #6366f1, #8b5cf6)';
                            btn.disabled = false;
                            btn.style.opacity = '1';
                        }}, 3000);
                    }}
                }}
                window.visualAnalyzeDashboard = visualAnalyzeDashboard;
                </script>
                
                <!-- Chart Grid (responsive) -->
                <style>
                    .chart-grid {{ 
                        display: flex; 
                        flex-wrap: wrap; 
                        gap: 1rem; 
                    }}
                    .chart-item {{
                        flex: 1 1 calc(50% - 0.5rem);
                        min-width: 300px;
                    }}
                    .chart-full-width {{ 
                        flex: 1 1 100%;
                    }}
                    @media (max-width: 768px) {{ 
                        .chart-item {{ flex: 1 1 100%; }} 
                    }}
                </style>
                <div id="charts-only" class="chart-grid">
                    <!-- Revenue/Profit Chart -->
                    <div class="chart-item" style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1rem; overflow: hidden;">
                        <h4 style="color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.75rem 0; text-align: center;">売上 / 営業利益</h4>
                        <div style="height: 220px; position: relative; width: 100%;">
                            <canvas id="{chart_id1}"></canvas>
                        </div>
                    </div>
                    
                    <!-- Cash Flow Chart -->
                    <div class="chart-item" style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1rem; overflow: hidden;">
                        <h4 style="color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.75rem 0; text-align: center;">キャッシュフロー推移</h4>
                        <div style="height: 220px; position: relative; width: 100%;">
                            <canvas id="{chart_id2}"></canvas>
                        </div>
                    </div>

                    <!-- Financial Health & Efficiency Chart (New) -->
                    <div class="chart-full-width" style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1rem; max-width: 100%; overflow: hidden;">
                        <h4 style="color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.75rem 0; text-align: center;">財務健全性・効率性 (ROE/ROA/有利子負債)</h4>
                        <div style="height: 220px; position: relative; width: 100%;">
                            <canvas id="{chart_id4}"></canvas>
                        </div>
                    </div>
                    
                    <!-- Growth & Quality Analysis (Moved from OOB) -->
                    <div class="chart-full-width" style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1rem; max-width: 100%; overflow: hidden;">
                        <h4 style="color: #10b981; font-size: 0.95rem; margin: 0 0 1rem 0; text-align: center; font-weight: 600;">🚀 成長性・クオリティ分析 (年率10%目標)</h4>
                        
                        <!-- Growth Charts & Scorecards (Copied Content) -->
                        <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 1rem;">
                            <!-- Growth vs Target Line Chart -->
                            <div style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1rem;">
                                <h4 style="color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.75rem 0; text-align: center;">売上高成長 vs 10%目標ライン</h4>
                                <div style="height: 250px; position: relative;">
                                    <canvas id="{chart_id3}"></canvas>
                                </div>
                                <p style="font-size: 0.7rem; color: #475569; margin-top: 0.5rem; text-align: center;">
                                    ※点線は5年前(または開始点)からの年率10%成長のシミュレーション
                                </p>
                            </div>
                            
                            <!-- Growth Scorecards -->
                            <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                                <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 12px; padding: 1rem;">
                                    <div style="color: #10b981; font-size: 0.75rem; font-weight: 600;">売上高 CAGR (3年)</div>
                                    <div style="font-size: 1.5rem; font-weight: 700; color: #f8fafc; margin-top: 0.25rem;">
                                        {f'{growth_analysis["revenue_cagr_3y"]}%' if pd.notna(growth_analysis["revenue_cagr_3y"]) else '-'}
                                    </div>
                                    <div style="font-size: 0.7rem; color: {'#10b981' if growth_analysis['is_high_growth'] else '#64748b'}; margin-top: 0.25rem;">
                                        {('✅ 10%目標達成' if growth_analysis['is_high_growth'] else '⚠️ 基準未達') if pd.notna(growth_analysis["revenue_cagr_3y"]) else 'データ不足'}
                                    </div>
                                </div>
                                
                                <div style="background: rgba(99, 102, 241, 0.1); border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 12px; padding: 1rem;">
                                    <div style="color: #818cf8; font-size: 0.75rem; font-weight: 600;">EPS CAGR (3年)</div>
                                    <div style="font-size: 1.5rem; font-weight: 700; color: #f8fafc; margin-top: 0.25rem;">
                                        {f'{growth_analysis["eps_cagr_3y"]}%' if pd.notna(growth_analysis["eps_cagr_3y"]) else '-'}
                                    </div>
                                    <div style="font-size: 0.7rem; color: #94a3b8; margin-top: 0.25rem;">
                                        連続増収: {growth_analysis["consecutive_growth_years"]}年
                                    </div>
                                </div>

                                <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 12px; padding: 1rem;">
                                    <div style="color: #f59e0b; font-size: 0.75rem; font-weight: 600;">利益率トレンド</div>
                                    <div style="font-size: 1.1rem; font-weight: 700; color: #f8fafc; margin-top: 0.25rem; text-transform: capitalize;">
                                        {growth_analysis["margin_trend"]}
                                    </div>
                                    <div style="font-size: 0.7rem; color: #94a3b8; margin-top: 0.25rem;">
                                        最新の収益安定性判定
                                    </div>
                                </div>
                            </div>
                        </div>
                </div>
                
                <!-- Chart.js Scripts -->
                <script>
                (function() {{
                    // Revenue/Profit Chart
                    new Chart(document.getElementById('{chart_id1}').getContext('2d'), {{
                        type: 'bar',
                        data: {{
                            labels: {years_label_js},
                            datasets: [
                                {{ label: '売上高', data: {revenue_data_js}, backgroundColor: 'rgba(99,102,241,0.7)', borderColor: '#6366f1', borderWidth: 1 }},
                                {{ label: '営業利益', data: {op_income_data_js}, backgroundColor: 'rgba(16,185,129,0.7)', borderColor: '#10b981', borderWidth: 1 }},
                                {{ label: '営業利益率(%)', data: {op_margin_data_js}, type: 'line', borderColor: '#f59e0b', borderWidth: 2, yAxisID: 'y1', tension: 0.3, pointRadius: 4 }}
                            ]
                        }},
                        options: {{
                            responsive: true, maintainAspectRatio: false,
                            interaction: {{ mode: 'index', intersect: false }},
                            scales: {{
                                y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, title: {{ display: true, text: '単位: 億円', color: '#64748b', font: {{ size: 10 }} }} }},
                                y1: {{ position: 'right', grid: {{ display: false }}, ticks: {{ color: '#f59e0b', font: {{ size: 10 }} }}, min: 0 }},
                                x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }} }}
                            }},
                            plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }} }}
                        }}
                    }});
                    
                    // Cash Flow Chart (Updated)
                    new Chart(document.getElementById('{chart_id2}').getContext('2d'), {{
                        type: 'bar',
                        data: {{
                            labels: {years_label_js},
                            datasets: [
                                {{ label: '営業CF', data: {op_cf_data_js}, backgroundColor: 'rgba(16,185,129,0.7)', borderColor: '#10b981', borderWidth: 1 }},
                                {{ label: '投資CF', data: {inv_cf_data_js}, backgroundColor: 'rgba(244,63,94,0.7)', borderColor: '#f43f5e', borderWidth: 1 }},
                                {{ label: '財務CF', data: {fin_cf_data_js}, backgroundColor: 'rgba(59,130,246,0.7)', borderColor: '#3b82f6', borderWidth: 1 }},
                                {{ label: 'フリーCF', data: {fcf_data_js}, type: 'line', borderColor: '#a855f7', borderWidth: 2, borderDash: [5, 5], tension: 0.3, pointRadius: 3, fill: false }},
                                {{ label: 'ネットCF', data: {net_cf_data_js}, type: 'line', borderColor: '#f59e0b', borderWidth: 3, tension: 0.4, pointRadius: 4, fill: false }}
                            ]
                        }},
                        options: {{
                            responsive: true, maintainAspectRatio: false,
                            interaction: {{ mode: 'index', intersect: false }},
                            scales: {{
                                y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, title: {{ display: true, text: '単位: 億円', color: '#64748b', font: {{ size: 10 }} }} }},
                                x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }} }}
                            }},
                            plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }} }}
                        }}
                    }});

                    // Financial Health & Efficiency Chart (New)
                    new Chart(document.getElementById('{chart_id4}').getContext('2d'), {{
                        type: 'bar',
                        data: {{
                            labels: {years_label_js},
                            datasets: [
                                {{ label: '有利子負債', data: {debt_data_js}, backgroundColor: 'rgba(251, 113, 133, 0.6)', borderColor: '#f43f5e', borderWidth: 1, yAxisID: 'y' }},
                                {{ label: 'ROE', data: {roe_data_js}, type: 'line', borderColor: '#818cf8', borderWidth: 2, yAxisID: 'y1', tension: 0.3, pointRadius: 4 }},
                                {{ label: 'ROA', data: {roa_data_js}, type: 'line', borderColor: '#2dd4bf', borderWidth: 2, yAxisID: 'y1', tension: 0.3, pointRadius: 4 }}
                            ]
                        }},
                        options: {{
                            responsive: true, maintainAspectRatio: false,
                            interaction: {{ mode: 'index', intersect: false }},
                            scales: {{
                                y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, title: {{ display: true, text: '単位: 億円', color: '#64748b', font: {{ size: 10 }} }} }},
                                y1: {{ position: 'right', grid: {{ display: false }}, ticks: {{ color: '#818cf8', font: {{ size: 10 }} }}, title: {{ display: true, text: '%', color: '#818cf8', font: {{ size: 10 }} }} }},
                                x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }} }}
                            }},
                            plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }} }}
                        }}
                    }});

                    // Growth Chart (Chart 3)
                    new Chart(document.getElementById('{chart_id3}').getContext('2d'), {{
                        type: 'bar',
                        data: {{
                            labels: {growth_labels_js},
                            datasets: [
                                {{
                                    label: '実績売上高',
                                    data: {growth_rev_actual_js},
                                    backgroundColor: 'rgba(16, 185, 129, 0.6)',
                                    borderColor: '#10b981',
                                    borderWidth: 1
                                }},
                                {{
                                    label: '10%成長目標',
                                    data: {growth_rev_target_js},
                                    type: 'line',
                                    borderColor: '#fbbf24',
                                    borderDash: [5, 5],
                                    borderWidth: 2,
                                    fill: false,
                                    pointRadius: 0
                                }},
                                {{
                                    label: 'ROE',
                                    data: {roe_data_js},
                                    type: 'line',
                                    borderColor: '#818cf8',
                                    borderWidth: 2,
                                    yAxisID: 'y1',
                                    tension: 0.3,
                                    pointRadius: 4
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: {{
                                y: {{ 
                                    grid: {{ color: 'rgba(255,255,255,0.05)' }},
                                    ticks: {{ color: '#64748b' }},
                                    title: {{ display: true, text: '億円', color: '#64748b' }}
                                }},
                                y1: {{ 
                                    position: 'right', 
                                    grid: {{ display: false }}, 
                                    ticks: {{ color: '#818cf8' }}, 
                                    title: {{ display: true, text: '% (ROE)', color: '#818cf8' }} 
                                }},
                                x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b' }} }}
                            }},
                            plugins: {{
                                legend: {{ labels: {{ color: '#94a3b8' }} }}
                            }}
                        }}
                    }});
                }})();
                </script>
            </div>
            </div><!-- Closes chart-section -->





            <!-- Financial Data Table (OOB Swap) -->
            <div id="financial-data-section" class="section" hx-swap-oob="true">
                <h2 style="font-family: 'Outfit', sans-serif; font-size: 1.2rem; margin-bottom: 1rem; color: #818cf8; text-align: center;">
                    📈 {name} 財務データ
                </h2>
                <div style="overflow-x: auto;">
                    <table style="width: 100%; font-size: 0.85rem;">
                        <thead>
                            <tr>
                                <th style="text-align: left; padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1);">年度</th>
                                <th style="text-align: right; padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1);">売上 (億円)</th>
                                <th style="text-align: right; padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1);">営業利益</th>
                                <th style="text-align: right; padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1);">純利益</th>
                                <th style="text-align: right; padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1);">EPS</th>
                                <th style="text-align: right; padding: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.1);">営業CF</th>
                            </tr>
                        </thead>
                        <tbody style="color: #e2e8f0;">
                            {table_rows if table_rows else '<tr><td colspan="6" style="text-align: center; padding: 2rem; color: #64748b;">データなし</td></tr>'}
                        </tbody>
                    </table>
                </div>
                <p style="font-size: 0.7rem; color: #475569; margin-top: 1rem; text-align: center;">
                    データソース: Yahoo Finance | 単位: 億円
                </p>
            </div>

            <!-- Clear cashflow section since we now show it inline -->
            <div id="cashflow-section" class="section" hx-swap-oob="true" style="display: none;"></div>

            <!-- Earnings Info Section (OOB Swap) -->
            {earnings_html}

            <!-- Discussion Board (OOB Swap) -->
            <div id="discussion-section" hx-swap-oob="outerHTML" style="display: block; margin-top: 1rem;">
                <div id="discussion-board-content" hx-get="/api/comments/{code_input}" hx-trigger="load" hx-swap="outerHTML">
                    <p style="color: #64748b; text-align: center; font-size: 0.85rem; padding: 2rem;">
                        掲示板を読み込み中...
                    </p>
                </div>
            </div>

            <!-- News Section (OOB Swap) - Restored for Sidebar -->
            <div id="news-section" hx-swap-oob="true" style="display: block; margin-top: 1rem;">
                <div hx-get="/api/news/{code_only}?name={urllib.parse.quote(name)}" hx-trigger="load delay:500ms" hx-swap="innerHTML">
                    <div class="flex items-center justify-center p-8 space-x-3 text-gray-400">
                        <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-green-400"></div>
                        <span class="text-sm font-medium">最新ニュースを取得中...</span>
                    </div>
                </div>
            </div>

            <!-- Favorite Button (OOB Swap) -->
            <div id="fav-button-container" hx-swap-oob="true" style="display: flex; align-items: center; margin-left: 0.5rem;">
                {fav_button}
            </div>
        """
        
        # Create response and set cookie to remember last searched ticker
        response = HTMLResponse(content=html_content)
        response.set_cookie(key="last_ticker", value=code_input, max_age=86400*30)  # 30 days
        return response
        
    except Exception as e:
        logger.error(f"Yahoo Finance lookup error for {code_input}: {e}")
        return HTMLResponse(content=f"""
            <div style="color: #fb7185; padding: 1rem; text-align: center; background: rgba(244, 63, 94, 0.1); border-radius: 8px;">
                ❌ データの取得に失敗しました: {str(e)}
            </div>
        """)


@app.post("/api/ai/analyze")
async def ai_analyze_stock(ticker_code: Annotated[str, Form()]):
    try:
        # 1. データの再取得（コンテキスト構築用）
        ticker = yf.Ticker(f"{ticker_code}.T")
        info = ticker.info
        name = info.get("longName") or info.get("shortName") or ticker_code
        
        # 財務履歴（最大4年）
        fin = ticker.financials
        summary_text = f"企業名: {name}\n"
        if not fin.empty:
            dates = sorted(fin.columns, reverse=True)[:3]
            for d in dates:
                rev = fin.loc["Total Revenue", d] if "Total Revenue" in fin.index else 0
                op = fin.loc["Operating Income", d] if "Operating Income" in fin.index else 0
                summary_text += f"- {d.year}年度: 売上 {rev/1e8:,.1f}億円, 営業利益 {op/1e8:,.1f}億円\n"
        
        # 投資指標
        summary_text += f"- 時価総額: {info.get('marketCap', 0)/1e8:,.0f}億円\n"
        summary_text += f"- PER: {info.get('trailingPE', '-')}\n"
        summary_text += f"- PBR: {info.get('priceToBook', '-')}\n"
        
        # 配当利回りの計算と補正
        div_yield = info.get('dividendYield', 0)
        div_rate = info.get('dividendRate', 0)
        price = info.get('currentPrice') or info.get('regularMarketPrice')
        
        # 自前計算を優先（APIのスケール不整合を防ぐ）
        if div_rate and price and price > 0:
            final_yield = div_rate / price
        elif div_yield:
            # API値が1以上(例: 2.5)なら%表記とみなし1/100にする、そうでなければそのまま
            final_yield = div_yield / 100.0 if div_yield > 1.0 else div_yield
        else:
            final_yield = 0
            
        summary_text += f"- 配当利回り: {final_yield*100:.2f}%\n"

        # 2. EDINETから定性情報を取得（既存ツールを流用）
        # 2. EDINETから定性情報を取得（Enhancedツールを使用）
        from utils.edinet_enhanced import search_company_reports, process_document
        edinet_ctx = {}
        try:
            # 有価証券報告書 (120) を過去1年分検索
            docs = search_company_reports(company_code=ticker_code, doc_type="120", days_back=365)
            
            # なければ四半期報告書 (140) を過去半年検索
            if not docs:
                docs = search_company_reports(company_code=ticker_code, doc_type="140", days_back=180)
            
            if docs:
                # 最新の書類を処理
                processed = process_document(docs[0])
                if processed:
                     edinet_ctx = processed
                     logger.info(f"EDINET context loaded for {ticker_code}: {len(edinet_ctx.get('text_data', {}))} text blocks")
        except Exception as ee:
            logger.error(f"EDINET fetch failed for AI analysis: {ee}")

        # 3. AI分析実行
        # EDINETから日本語の企業名を優先的に使用
        japanese_name = edinet_ctx.get("metadata", {}).get("company_name")
        company_name_for_ai = japanese_name if japanese_name else name
        
        financial_context = {
            "summary_text": summary_text,
            "edinet_data": edinet_ctx
        }
        
        report_html = analyze_stock_with_ai(ticker_code, financial_context, company_name=company_name_for_ai)
        
        # 中身だけ返す (hx-target="#ai-analysis-content")
        return HTMLResponse(content=report_html)

    except Exception as e:
        logger.error(f"AI Analysis endpoint error: {e}")
        return HTMLResponse(content=f"<p style='color: #fb7185;'>AI分析中にエラーが発生しました: {str(e)}</p>")

@app.get("/api/news/{ticker_code}")
async def get_stock_news(ticker_code: str, name: Optional[str] = Query(None)):
    try:
        # Use provided name or fetch if missing
        if not name:
            ticker = yf.Ticker(f"{ticker_code}.T")
            info = ticker.info
            name = info.get("longName") or info.get("shortName") or ticker_code
        
        # Fetch news
        from utils.news import fetch_company_news
        news_items = fetch_company_news(name)
        
        if not news_items:
            return HTMLResponse(content="<div style='color: var(--text-dim); text-align: center; padding: 2rem;'>関連ニュースは見つかりませんでした</div>")
            
        # Render News Cards
        html = f"""
        <div style="display: flex; flex-direction: column; gap: 1rem;">
            <h3 style="font-family: 'Outfit', sans-serif; font-size: 1.1rem; color: var(--accent); display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
                <span>📰</span>
                <span>最新ニュース</span>
                <span style="font-size: 0.7rem; color: var(--text-dim); font-weight: normal; margin-left: auto;">Google News</span>
            </h3>
            <div style="display: flex; flex-direction: column; gap: 0.75rem;">
        """
        
        for item in news_items:
            html += f"""
            <a href="{item['link']}" target="_blank" style="text-decoration: none; display: block;">
                <div style="background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: 12px; padding: 1rem; transition: all 0.2s;" 
                     onmouseover="this.style.borderColor='var(--accent)'; this.style.transform='translateY(-2px)';" 
                     onmouseout="this.style.borderColor='var(--glass-border)'; this.style.transform='none';">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                        <span style="font-size: 0.7rem; font-weight: 600; color: var(--success); background: rgba(16, 185, 129, 0.1); padding: 0.2rem 0.5rem; border-radius: 4px;">{item['source']}</span>
                        <span style="font-size: 0.7rem; color: var(--text-dim);">{item['published']}</span>
                    </div>
                    <h4 style="font-size: 0.9rem; font-weight: 600; color: var(--text-main); line-height: 1.4; margin: 0; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">
                        {item['title']}
                    </h4>
                </div>
            </a>
            """
            
        html += "</div></div>"
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"News API error: {e}")
        return HTMLResponse(content="<div style='color: var(--text-dim); font-size: 0.8rem; text-align: center;'>ニュースの取得中に一時的なエラーが発生しました</div>")
@app.get("/ai-policy")
async def ai_policy(request: Request):
    """Serve the AI policy page"""
    return templates.TemplateResponse("ai_policy.html", {"request": request})

@app.post("/api/edinet/search")
async def search_edinet_company(
    company_name: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search company financial data from EDINET (Latest)"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:

        
        # Determine search type: Code or Name
        clean_query = company_name.strip().replace(".T", "").replace("Ｔ", "") # Handle wide chars too just in case
        is_code = clean_query.isdigit()
        
        # Search for documents (Annual Report 120 first)
        if is_code:
            logger.info(f"Searching EDINET by code: {clean_query}")
            # Ensure it's executed in threadpool for non-blocking
            docs = await run_in_threadpool(search_company_reports, company_code=clean_query, doc_type="120", days_back=365)
            if not docs:
                docs = await run_in_threadpool(search_company_reports, company_code=clean_query, doc_type="140", days_back=180)
        else:
             logger.info(f"Searching EDINET by name: {company_name}")
             docs = await run_in_threadpool(search_company_reports, company_name=company_name, doc_type="120", days_back=365)
             if not docs:
                # Try quarterly report
                docs = await run_in_threadpool(search_company_reports, company_name=company_name, doc_type="140", days_back=180)
        
        if not docs:
            return HTMLResponse(content=f"""
                <div class="alert alert-error">
                    ❌ 「{company_name}」の書類が見つかりませんでした。
                </div>
            """)
        
        doc = docs[0]
        sec_code = doc.get("secCode", "")
        
        # Process document
        result = process_document(doc)
        
        if not result:
             return HTMLResponse(content="""
                <div class="alert alert-error">
                    ❌ データの取得・解析に失敗しました。
                </div>
            """)
            
        metadata = result.get("metadata", {})
        normalized = result.get("normalized_data", {})
        
        text_data = result.get("text_data", {})
        website_url = result.get("website_url")
        formatted_normalized = format_financial_data(normalized)

        # Fetch Sector & Scale Tag Badges
        sector_badges_html = ""
        try:
            if sec_code:
                # Handle 5-digit code (e.g. 72030 -> 7203)
                clean_code = sec_code[:-1] if len(sec_code) == 5 and sec_code.endswith("0") else sec_code
                
                # Query DB
                comp = db.query(Company).filter(Company.code_4digit == clean_code).first()
                if comp:
                    badges = []
                    # Sector 33 (e.g. 食料品) - Blue badge
                    if comp.sector_33:
                         badges.append(f'<span class="px-2 py-0.5 rounded text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">{comp.sector_33}</span>')
                    
                    # Sector 17 (e.g. 食品) - Purple badge
                    if comp.sector_17 and comp.sector_17 != comp.sector_33: # Avoid dup if same
                        badges.append(f'<span class="px-2 py-0.5 rounded text-xs font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">{comp.sector_17}</span>')
                    
                    # Scale Category (e.g. TOPIX Mid400)
                    if comp.scale_category:
                         scale = comp.scale_category
                         # Friendly Name Logic
                         s_text = scale
                         s_color = "gray" # Default
                         
                         if "Core30" in scale:
                             s_text = "超大型 (Core30)"
                             s_color = "red"
                         elif "Large70" in scale:
                             s_text = "大型 (Large70)"
                             s_color = "orange"
                         elif "Mid400" in scale:
                             s_text = "中型 (Mid400)"
                             s_color = "yellow"
                         elif "Small" in scale:
                             small_num = scale.replace("TOPIX Small", "").strip() 
                             s_text = f"小型 ({small_num})"
                             s_color = "emerald"
                         
                         badges.append(f'<span class="px-2 py-0.5 rounded text-xs font-medium bg-{s_color}-500/10 text-{s_color}-400 border border-{s_color}-500/20">{s_text}</span>')
                    
                    if badges:
                        sector_badges_html = f'<div class="flex flex-wrap gap-2 mt-2">{"".join(badges)}</div>'

        except Exception as e:
            logger.error(f"Error fetching badges: {e}")
        
        # Qualitative Information Sections - Grid Layout
        sections_html = ""
        # Add instruction
        sections_html += '<p style="color: #64748b; font-size: 0.8rem; margin-bottom: 0.75rem;">▼ をクリックして展開（📋 でコピー）</p>'
        # Start Grid Container
        sections_html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem;">'
        # Display order: Business overview -> Strategy -> Financial Analysis -> Risks -> Operations
        text_keys = [
            "事業の内容",
            "経営方針・経営戦略", 
            "経営者による分析",
            # New financial-focused sections
            "財政状態の分析",
            "経営成績の分析",
            "キャッシュフローの状況",
            "経理の状況",
            "重要な会計方針",
            # Other sections
            "事業等のリスク",
            "対処すべき課題",
            "研究開発活動",
            "設備投資の状況",
            "従業員の状況",
            "コーポレートガバナンス",
            "サステナビリティ"
        ]
        
        for idx, key in enumerate(text_keys):
            content = text_data.get(key)
            if content:
                section_id = f"edinet-text-{idx}"
                copy_btn_id = f"copy-btn-{idx}"
                # HTML for expandable section with copy button
                # Escape content for safe embedding in data attribute
                import html
                escaped_content = html.escape(content)
                
                sections_html += f"""
                <details class="bg-gray-900/30 rounded-lg border border-gray-700/50 overflow-hidden" style="height: fit-content;">
                    <summary class="cursor-pointer px-4 py-3 bg-gray-800/50 hover:bg-gray-700/50 transition-colors font-medium text-gray-200 list-none flex items-center gap-3">
                        <span style="font-size: 0.9rem;">{key}</span>
                        <button 
                            id="{copy_btn_id}"
                            onclick="event.stopPropagation(); event.preventDefault(); copyToClipboard('{section_id}', '{copy_btn_id}');"
                            style="background: transparent; border: none; padding: 2px; cursor: pointer; color: #64748b; display: flex; align-items: center; opacity: 0.7;"
                            onmouseover="this.style.opacity='1'; this.style.color='#818cf8';"
                            onmouseout="this.style.opacity='0.7'; this.style.color='#64748b';"
                            title="クリップボードにコピー">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                        </button>
                    </summary>
                    <div id="{section_id}" class="p-4 text-sm text-gray-200 leading-relaxed border-t border-gray-700/50 bg-gray-900/50" style="white-space: pre-wrap; max-height: 400px; overflow-y: auto;">
                        {content}
                    </div>
                </details>
                """
        
        # Close Grid Container
        sections_html += '</div>'

        history_btn = ""  # Disabled - removed the financial chart button
        
        # Website link HTML
        website_html = ""
        if website_url:
            website_html = f'<a href="{website_url}" target="_blank" rel="noopener" class="text-blue-400 hover:text-blue-300 underline text-sm">企業サイト</a>'

        # AI Analysis Buttons - Elegant Glassmorphism Design
        ai_btn = ""
        if sec_code:
            code_only = sec_code[:4]
            cname = metadata.get('company_name', '').replace('"', '&quot;')
            ai_btn = f"""
            <div style="margin-top: 2rem; padding: 1.5rem; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(12px); border-radius: 16px; border: 1px solid rgba(99, 102, 241, 0.2);">
                <div style="display: flex; align-items: center; justify-content: center; gap: 0.5rem; margin-bottom: 0.5rem;">
                    <span style="font-size: 1.25rem;">🤖</span>
                    <h4 style="font-size: 1rem; font-weight: 600; color: #e2e8f0; margin: 0;">AI投資分析</h4>
                </div>
                <p style="text-align: center; color: #64748b; font-size: 0.75rem; margin-bottom: 1rem;">3つの専門視点で企業を評価</p>
                <div id="ai-analysis-container">
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: center;">
                        <button id="ai-fin-{code_only}" class="ai-btn ai-btn-blue"
                            style="padding: 0.5rem 1rem; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.3); color: #60a5fa; border-radius: 6px; font-weight: 500; font-size: 0.8rem; cursor: pointer; transition: all 0.2s;"
                            hx-post="/api/ai/analyze-financial"
                            hx-target="#ai-result"
                            hx-vals='{{"code": "{code_only}", "name": "{cname}"}}'
                            data-original="💰 財務健全性"
                            onclick="this.innerText='⏳ 分析中...';"
                            hx-on::after-request="this.innerText=this.dataset.original">
                            💰 財務健全性
                        </button>
                        
                        <button id="ai-biz-{code_only}" class="ai-btn ai-btn-green"
                            style="padding: 0.5rem 1rem; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); color: #34d399; border-radius: 6px; font-weight: 500; font-size: 0.8rem; cursor: pointer; transition: all 0.2s;"
                            hx-post="/api/ai/analyze-business"
                            hx-target="#ai-result"
                            hx-vals='{{"code": "{code_only}", "name": "{cname}"}}'
                            data-original="🚀 事業競争力"
                            onclick="this.innerText='⏳ 分析中...';"
                            hx-on::after-request="this.innerText=this.dataset.original">
                            🚀 事業競争力
                        </button>
                        <button id="ai-rsk-{code_only}" class="ai-btn ai-btn-red"
                            style="padding: 0.5rem 1rem; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171; border-radius: 6px; font-weight: 500; font-size: 0.8rem; cursor: pointer; transition: all 0.2s;"
                            hx-post="/api/ai/analyze-risk"
                            hx-target="#ai-result"
                            hx-vals='{{"code": "{code_only}", "name": "{cname}"}}'
                            data-original="⚠️ リスク分析"
                            onclick="this.innerText='⏳ 分析中...';"
                            hx-on::after-request="this.innerText=this.dataset.original">
                            ⚠️ リスク分析
                        </button>
                    </div>
                    <style>
                        #ai-fin-{code_only}:hover {{ background: rgba(59, 130, 246, 0.2); }}
                        #ai-biz-{code_only}:hover {{ background: rgba(16, 185, 129, 0.2); }}
                        #ai-rsk-{code_only}:hover {{ background: rgba(239, 68, 68, 0.2); }}
                    </style>
                    <div id="ai-result" style="margin-top: 1rem; padding: 1rem; background: rgba(30, 41, 59, 0.4); border-radius: 8px; border: 1px solid rgba(71, 85, 105, 0.3); color: #94a3b8; line-height: 1.6; font-size: 0.875rem; min-height: 60px; text-align: left;">
                        分析したい視点を選択してください
                    </div>
                    
                    <a href="#" onclick="window.open('/ai-policy', '_blank'); return false;" style="display: block; text-align: right; margin-top: 0.5rem; color: #64748b; font-size: 0.7rem; text-decoration: underline; cursor: pointer;" onmouseover="this.style.color='#94a3b8'" onmouseout="this.style.color='#64748b'">
                        AI生成コンテンツに関する免責事項
                    </a>
                </div>
            </div>
            """
        
        return HTMLResponse(content=f"""
            <div class="bg-gray-800/80 backdrop-blur-md border border-gray-700 rounded-xl p-6 shadow-2xl animate-fade-in-up">
                <div class="flex items-start justify-between mb-6 pb-4 border-b border-gray-700">
                    <div>
                        <div class="flex items-center gap-3">
                            <h3 class="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-300">
                                {metadata.get('company_name')}
                            </h3>
                            <span class="px-2 py-1 bg-gray-700 text-gray-300 text-xs font-mono rounded-md border border-gray-600">{sec_code}</span>
                            {website_html}
                        </div>
                        {sector_badges_html}
                        <div class="flex items-center gap-2 mt-2 text-sm text-gray-400">
                            <span class="bg-gray-900/50 px-2 py-1 rounded">{metadata.get('document_type')}</span>
                            <span class="text-xs text-gray-500">提出: {metadata.get('submit_date')}</span>
                            {'<span class="text-xs text-green-400 bg-green-900/30 px-2 py-1 rounded">⚡ キャッシュ</span>' if metadata.get('from_cache') else ''}
                        </div>
                    </div>
                </div>
                
                <!-- Key Financials Summary Removed by Request -->
                
                <h4 class="text-lg font-bold text-gray-200 mb-4 border-l-4 border-indigo-500 pl-3">
                    定性情報レポート
                </h4>
                
                {sections_html if sections_html else "<div class='text-gray-500 p-4 text-center bg-gray-900/30 rounded-lg'>詳細なテキスト情報はこのドキュメントに含まれていません。</div>"}
                
                {history_btn}
                {ai_btn}

                <!-- Hidden trigger to load history charts automatically -->
                <div hx-get="/api/edinet/history/{sec_code}" 
                     hx-trigger="load delay:500ms" 
                     hx-swap="none">
                </div>
                
                <!-- Copy to Clipboard JavaScript -->
                <script>
                    function copyToClipboard(sectionId, btnId) {{
                        const content = document.getElementById(sectionId);
                        const button = document.getElementById(btnId);
                        
                        if (!content) return;
                        
                        // Get text content
                        const text = content.innerText || content.textContent;
                        
                        // Copy to clipboard
                        navigator.clipboard.writeText(text).then(() => {{
                            // Success feedback - icon color green
                            button.classList.remove('text-gray-500', 'hover:text-indigo-400');
                            button.classList.add('text-green-500');
                            
                            // Reset after 1.5 seconds
                            setTimeout(() => {{
                                button.classList.remove('text-green-500');
                                button.classList.add('text-gray-500', 'hover:text-indigo-400');
                            }}, 1500);
                        }}).catch(err => {{
                            console.error('コピー失敗:', err);
                            // Error feedback - icon color red
                            button.classList.remove('text-gray-500', 'hover:text-indigo-400');
                            button.classList.add('text-red-500');
                            setTimeout(() => {{
                                button.classList.remove('text-red-500');
                                button.classList.add('text-gray-500', 'hover:text-indigo-400');
                            }}, 1500);
                        }});
                    }}
                </script>
            </div>
        """)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"""
            <div class="alert alert-error">
                ❌ エラー: {str(e)}
            </div>
        """, status_code=500)



@app.post("/api/ai/analyze", response_class=HTMLResponse)
def api_ai_analyze(
    ticker_code: str = Form(...),
    force_refresh: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """AI Analysis Endpoint with caching - saves API costs"""
    if not current_user:
        return "<div class='text-red-400'>エラー: ログインが必要です</div>"

    try:
        clean_code = ticker_code.replace(".T", "")
        analysis_type = "general"
        cache_days = 7
        
        # Check cache first (unless force_refresh)
        if force_refresh != "true":
            cached = db.query(AIAnalysisCache).filter(
                AIAnalysisCache.ticker_code == clean_code,
                AIAnalysisCache.analysis_type == analysis_type,
                AIAnalysisCache.expires_at > datetime.utcnow()
            ).first()
            
            if cached:
                logger.info(f"[AI Cache HIT] {clean_code} - returning cached result")
                cache_date = cached.created_at.strftime("%Y-%m-%d %H:%M") if cached.created_at else "不明"
                
                # Return cached result with cache badge and copy button
                return f"""
                <div style="margin-bottom: 1rem; display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                    <span style="background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.75rem;">
                        ⚡ キャッシュから取得 ({cache_date})
                    </span>
                    <button onclick="copyAIAnalysis()" style="background: rgba(99, 102, 241, 0.2); color: #818cf8; border: none; padding: 0.25rem 0.75rem; border-radius: 6px; font-size: 0.75rem; cursor: pointer;">
                        📋 コピー
                    </button>
                    <button hx-post="/api/ai/analyze" hx-vals='{{"ticker_code": "{clean_code}", "force_refresh": "true"}}' hx-target="#ai-analysis-content" hx-swap="innerHTML" hx-indicator="#ai-loading" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: none; padding: 0.25rem 0.75rem; border-radius: 6px; font-size: 0.75rem; cursor: pointer;">
                        🔄 最新で再分析
                    </button>
                </div>
                <div id="ai-analysis-text">{cached.analysis_html}</div>
                <script>
                    function copyAIAnalysis() {{
                        const el = document.getElementById('ai-analysis-text');
                        const text = el.innerText || el.textContent;
                        navigator.clipboard.writeText(text).then(() => {{
                            alert('コピーしました！');
                        }}).catch(err => {{
                            // Fallback for mobile
                            const range = document.createRange();
                            range.selectNodeContents(el);
                            const selection = window.getSelection();
                            selection.removeAllRanges();
                            selection.addRange(range);
                            alert('テキストを選択しました。手動でコピーしてください。');
                        }});
                    }}
                </script>
                """
        
        # Cache miss or force refresh - generate new analysis
        logger.info(f"[AI Cache MISS] {clean_code} - generating new analysis")
        
        # Context data preparation
        financial_context = {}
        company_name = f"Code: {clean_code}"
        
        # Fetch latest financial data for context
        history = get_financial_history(company_code=clean_code, years=1)
        if history and len(history) > 0:
            data = history[0]
            # Generate summary text using the fixed formatter
            summary_text = _format_summary(data.get("normalized_data", {}))
            
            # Build context correctly for ai_analysis
            financial_context = {
                "summary_text": summary_text,
                "edinet_data": data, # Complete data including text_data
                "normalized_data": data.get("normalized_data", {})
            }
            meta = data.get("metadata", {})
            company_name = meta.get("company_name", company_name)
        
        # Execute Analysis (returns HTML)
        analysis_html = analyze_stock_with_ai(clean_code, financial_context, company_name)
        
        # Save to cache (upsert)
        existing = db.query(AIAnalysisCache).filter(
            AIAnalysisCache.ticker_code == clean_code,
            AIAnalysisCache.analysis_type == analysis_type
        ).first()
        
        if existing:
            existing.analysis_html = analysis_html
            existing.created_at = datetime.utcnow()
            existing.expires_at = datetime.utcnow() + timedelta(days=cache_days)
        else:
            new_cache = AIAnalysisCache(
                ticker_code=clean_code,
                analysis_type=analysis_type,
                analysis_html=analysis_html,
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=cache_days)
            )
            db.add(new_cache)
        db.commit()
        logger.info(f"[AI Cache SAVED] {clean_code} - cached for {cache_days} days")
        
        # Return new result with copy button
        gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""
        <div style="margin-bottom: 1rem; display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
            <span style="background: rgba(99, 102, 241, 0.2); color: #818cf8; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.75rem;">
                🆕 新規生成 ({gen_date})
            </span>
            <button onclick="copyAIAnalysis()" style="background: rgba(99, 102, 241, 0.2); color: #818cf8; border: none; padding: 0.25rem 0.75rem; border-radius: 6px; font-size: 0.75rem; cursor: pointer;">
                📋 コピー
            </button>
        </div>
        <div id="ai-analysis-text">{analysis_html}</div>
        <script>
            function copyAIAnalysis() {{
                const el = document.getElementById('ai-analysis-text');
                const text = el.innerText || el.textContent;
                navigator.clipboard.writeText(text).then(() => {{
                    alert('コピーしました！');
                }}).catch(err => {{
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    alert('テキストを選択しました。手動でコピーしてください。');
                }});
            }}
        </script>
        """
        
    except Exception as e:
        logger.error(f"AI Analysis error: {e}")
        import traceback
        traceback.print_exc()
        return f"<div class='text-red-400'>AI分析中にエラーが発生しました: {str(e)}</div>"

def _format_summary(normalized: dict) -> str:
    """Format normalized financial data into readable summary text for AI"""
    lines = []
    
    # Key metrics mapping
    key_metrics = {
        "売上高": "revenue",
        "営業利益": "operating_income", 
        "経常利益": "ordinary_income",
        "当期純利益": "net_income",
        "営業CF": "operating_cf",
        "投資CF": "investing_cf",
        "財務CF": "financing_cf",
        "フリーCF": "free_cf",
        "自己資本比率": "equity_ratio",
        "ROE": "roe",
        "ROA": "roa",
        "EPS": "eps",
    }
    
    for label, _ in key_metrics.items():
        val = normalized.get(label)
        if val is not None:
            if isinstance(val, (int, float)):
                if abs(val) >= 100000000:  # 1億以上
                    lines.append(f"{label}: {val/100000000:.1f}億円")
                elif isinstance(val, float) and abs(val) < 10:  # 割合っぽい (e.g. 0.318) - changed condition to < 10 to catch single digit ratios
                    # Note: formatted_data in extract uses < 100 condition.
                    # Here we want to handle raw values.
                    # Ratios in normalized_data are usually raw floats (0.15) or percentage strings ("15%")?
                    # extract_financial_data sets them as raw values from XBRL.
                    # If XBRL says 0.15, it's 0.15.
                    if 0 < abs(val) < 1: # Decimal like 0.3
                         lines.append(f"{label}: {val*100:.1f}%")
                    elif 1 <= abs(val) < 100: # Percentage like 15.0? Or small number?
                         # Difficulty: EPS is small number. ROE is small number.
                         if label in ["ROE", "ROA", "自己資本比率", "配当性向"]:
                              lines.append(f"{label}: {val:.1f}%")
                         else:
                              lines.append(f"{label}: {val}")
                else:
                    lines.append(f"{label}: {val:,.0f}")
            else:
                lines.append(f"{label}: {val}")
    
    return "\n".join(lines) if lines else "財務データなし"

# Helper function for specialized AI analysis with caching
def _run_specialized_analysis(
    analysis_func,
    analysis_type: str,
    code: str,
    name: str,
    db: Session,
    user: User = None
):
    """Common logic for specialized AI analysis with caching and usage tracking"""
    cache_days = 7
    clean_code = code.replace(".T", "")

    # Check cache
    cached = db.query(AIAnalysisCache).filter(
        AIAnalysisCache.ticker_code == clean_code,
        AIAnalysisCache.analysis_type == analysis_type,
        AIAnalysisCache.expires_at > datetime.utcnow()
    ).first()

    if cached:
        logger.info(f"[AI Cache HIT] {clean_code}/{analysis_type}")
        cache_date = cached.created_at.strftime("%Y-%m-%d %H:%M") if cached.created_at else ""
        return f"""
        <div style='margin-bottom: 0.5rem;'>
            <span style='background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem;'>⚡ キャッシュ ({cache_date})</span>
            <button onclick="navigator.clipboard.writeText(this.parentElement.nextElementSibling.innerText).then(()=>alert('コピーしました'))" style="margin-left: 0.5rem; background: rgba(99,102,241,0.2); color: #818cf8; border: none; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem; cursor: pointer;">📋 コピー</button>
        </div>
        <div>{cached.analysis_html}</div>
        """

    # Check AI usage limit before generating new analysis
    if user and not check_ai_usage_limit(db, user):
        tier = get_user_tier(user)
        limit = get_feature_limit(user, "ai_analyses")
        usage = get_ai_usage_today(db, user)
        return f"""
            <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 12px; padding: 1.5rem; text-align: center; margin: 1rem 0;">
                <h3 style="color: #f59e0b; margin-bottom: 1rem;">⭐ 本日のAI分析上限に達しました</h3>
                <p style="color: #94a3b8; margin-bottom: 0.5rem;">
                    現在のプラン（{get_tier_display_name(tier)}）では1日{limit}回まで利用できます。
                </p>
                <p style="color: #94a3b8; margin-bottom: 1rem;">
                    本日の利用回数: {usage}/{limit}回
                </p>
                <a href="/premium" style="display: inline-block; padding: 0.75rem 1.5rem; background: linear-gradient(135deg, #f59e0b, #d97706); color: white; text-decoration: none; border-radius: 8px; font-weight: 600; transition: all 0.3s ease;">
                    プレミアムプランにアップグレード
                </a>
            </div>
        """

    # Generate new
    logger.info(f"[AI Cache MISS] {clean_code}/{analysis_type} - generating")

    # Increment usage counter BEFORE API call
    if user:
        increment_ai_usage(db, user)
        logger.info(f"[AI Usage] User {user.username} - {get_ai_usage_today(db, user)}/{get_feature_limit(user, 'ai_analyses')}")
    
    # Get financial context - include both numeric and text data
    financial_context = {}
    history = get_financial_history(company_code=clean_code, years=1)
    if history and len(history) > 0:
        data = history[0]
        normalized = data.get("normalized_data", {})
        text_data = data.get("text_data", {})
        metadata = data.get("metadata", {})
        
        # Build comprehensive context for AI
        financial_context = {
            **normalized,  # Include all numeric data
            "summary_text": _format_summary(normalized),  # Create summary text
            "edinet_data": {
                "text_data": text_data,
                "metadata": metadata
            }
        }
        logger.info(f"Financial context built with {len(normalized)} metrics and {len(text_data)} text blocks")
    
    # Call the specific analysis function
    result_html = analysis_func(clean_code, financial_context, name)
    
    # Save to cache
    existing = db.query(AIAnalysisCache).filter(
        AIAnalysisCache.ticker_code == clean_code,
        AIAnalysisCache.analysis_type == analysis_type
    ).first()
    
    if existing:
        existing.analysis_html = result_html
        existing.created_at = datetime.utcnow()
        existing.expires_at = datetime.utcnow() + timedelta(days=cache_days)
    else:
        new_cache = AIAnalysisCache(
            ticker_code=clean_code,
            analysis_type=analysis_type,
            analysis_html=result_html,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=cache_days)
        )
        db.add(new_cache)
    db.commit()
    logger.info(f"[AI Cache SAVED] {clean_code}/{analysis_type}")
    
    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""
    <div style='margin-bottom: 0.5rem;'>
        <span style='background: rgba(99, 102, 241, 0.2); color: #818cf8; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem;'>🆕 新規生成 ({gen_date})</span>
        <button onclick="navigator.clipboard.writeText(this.parentElement.nextElementSibling.innerText).then(()=>alert('コピーしました'))" style="margin-left: 0.5rem; background: rgba(99,102,241,0.2); color: #818cf8; border: none; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem; cursor: pointer;">📋 コピー</button>
    </div>
    <div>{result_html}</div>
    """

@app.post("/api/ai/analyze-financial", response_class=HTMLResponse)
def api_ai_analyze_financial(
    code: str = Form(...),
    name: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """💰 Financial health analysis endpoint"""
    if not current_user:
        return "<div class='text-red-400'>ログインが必要です</div>"
    try:
        return _run_specialized_analysis(analyze_financial_health, "financial", code, name, db, current_user)
    except Exception as e:
        logger.error(f"Financial analysis error: {e}")
        return f"<div class='text-red-400'>エラー: {str(e)}</div>"

@app.post("/api/ai/analyze-business", response_class=HTMLResponse)
def api_ai_analyze_business(
    code: str = Form(...),
    name: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🚀 Business competitiveness analysis endpoint"""
    if not current_user:
        return "<div class='text-red-400'>ログインが必要です</div>"
    try:
        return _run_specialized_analysis(analyze_business_competitiveness, "business", code, name, db, current_user)
    except Exception as e:
        logger.error(f"Business analysis error: {e}")
        return f"<div class='text-red-400'>エラー: {str(e)}</div>"

@app.post("/api/ai/analyze-risk", response_class=HTMLResponse)
def api_ai_analyze_risk(
    code: str = Form(...),
    name: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """⚠️ Risk & governance analysis endpoint"""
    if not current_user:
        return "<div class='text-red-400'>ログインが必要です</div>"
    try:
        return _run_specialized_analysis(analyze_risk_governance, "risk", code, name, db, current_user)
    except Exception as e:
        logger.error(f"Risk analysis error: {e}")
        return f"<div class='text-red-400'>エラー: {str(e)}</div>"


@app.post("/api/ai/visual-analyze")
async def api_ai_visual_analyze(
    image_data: str = Form(...),
    ticker_code: str = Form(...),
    company_name: str = Form(""),
    force_refresh: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📊 Visual dashboard analysis using Gemini multimodal with caching - returns HTML"""
    from fastapi.responses import HTMLResponse
    from utils.ai_analysis import (
        analyze_dashboard_image,
        render_visual_analysis_html,
        get_analysis_history,
        analyze_trend,
        render_trend_comparison_html
    )
    import json

    if not current_user:
        return HTMLResponse(content="<p class='error' style='color: #fb7185;'>ログインが必要です</p>", status_code=401)

    try:
        clean_code = ticker_code.replace(".T", "")
        analysis_type = "visual"
        cache_days = 7

        # Check cache first (unless force refresh requested)
        if not force_refresh:
            cached = db.query(AIAnalysisCache).filter(
                AIAnalysisCache.ticker_code == clean_code,
                AIAnalysisCache.analysis_type == analysis_type,
                AIAnalysisCache.expires_at > datetime.utcnow()
            ).first()

            if cached:
                logger.info(f"[Visual Cache HIT] {clean_code}")
                try:
                    # Parse stored JSON
                    analysis_data = json.loads(cached.analysis_html)

                    # Phase 3: Get history and analyze trend
                    history = get_analysis_history(db, clean_code, analysis_type, limit=10)
                    trend_data = analyze_trend(history)

                    # Render HTML from cached JSON
                    html = render_visual_analysis_html(analysis_data, is_from_cache=True)

                    # Add trend comparison if available
                    if trend_data.get("has_trend"):
                        trend_html = render_trend_comparison_html(trend_data)
                        html = trend_html + html

                    return HTMLResponse(content=html)
                except json.JSONDecodeError:
                    # Fallback: if cached data is old markdown format, regenerate
                    logger.warning(f"[Visual Cache] Invalid JSON for {clean_code}, regenerating")

        logger.info(f"[Visual Cache MISS] {clean_code} - generating new analysis")

        # Check AI usage limit before generating new analysis
        if not check_ai_usage_limit(db, current_user):
            tier = get_user_tier(current_user)
            limit = get_feature_limit(current_user, "ai_analyses")
            usage = get_ai_usage_today(db, current_user)
            return HTMLResponse(content=f"""
                <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 12px; padding: 1.5rem; text-align: center; margin: 1rem 0;">
                    <h3 style="color: #f59e0b; margin-bottom: 1rem;">⭐ 本日のAI分析上限に達しました</h3>
                    <p style="color: #94a3b8; margin-bottom: 0.5rem;">
                        現在のプラン（{get_tier_display_name(tier)}）では1日{limit}回まで利用できます。
                    </p>
                    <p style="color: #94a3b8; margin-bottom: 1rem;">
                        本日の利用回数: {usage}/{limit}回
                    </p>
                    <a href="/premium" style="display: inline-block; padding: 0.75rem 1.5rem; background: linear-gradient(135deg, #f59e0b, #d97706); color: white; text-decoration: none; border-radius: 8px; font-weight: 600; transition: all 0.3s ease;">
                        プレミアムプランにアップグレード
                    </a>
                </div>
            """, status_code=200)

        # Validate image data exists
        if not image_data or len(image_data) < 100:
            return HTMLResponse(content="<p class='error' style='color: #fb7185;'>画像データが無効です</p>", status_code=400)

        # Increment usage counter BEFORE API call
        increment_ai_usage(db, current_user)
        logger.info(f"[AI Usage] User {current_user.username} - {get_ai_usage_today(db, current_user)}/{get_feature_limit(current_user, 'ai_analyses')}")

        # Call the visual analysis function - returns dict (StructuredAnalysisResult)
        analysis_data = analyze_dashboard_image(image_data, clean_code, company_name)

        # Phase 2: Save to history table
        from utils.ai_analysis import save_analysis_to_history
        save_analysis_to_history(db, clean_code, analysis_type, analysis_data)

        # Save to cache (store JSON string)
        existing = db.query(AIAnalysisCache).filter(
            AIAnalysisCache.ticker_code == clean_code,
            AIAnalysisCache.analysis_type == analysis_type
        ).first()

        json_string = json.dumps(analysis_data, ensure_ascii=False)

        if existing:
            existing.analysis_html = json_string  # Store JSON string
            existing.created_at = datetime.utcnow()
            existing.expires_at = datetime.utcnow() + timedelta(days=cache_days)
        else:
            new_cache = AIAnalysisCache(
                ticker_code=clean_code,
                analysis_type=analysis_type,
                analysis_html=json_string,  # Store JSON string
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=cache_days)
            )
            db.add(new_cache)
        db.commit()
        logger.info(f"[Visual Cache SAVED] {clean_code}")

        # Phase 3: Get history and analyze trend
        history = get_analysis_history(db, clean_code, analysis_type, limit=10)
        trend_data = analyze_trend(history)

        # Render HTML from analysis data
        html = render_visual_analysis_html(analysis_data, is_from_cache=False)

        # Add trend comparison if available
        if trend_data.get("has_trend"):
            trend_html = render_trend_comparison_html(trend_data)
            html = trend_html + html

        return HTMLResponse(content=html)

    except ValueError as ve:
        logger.error(f"Visual analysis validation error: {ve}")
        return HTMLResponse(content=f"<p class='error' style='color: #fb7185;'>{str(ve)}</p>", status_code=400)
    except Exception as e:
        logger.error(f"Visual analysis error: {e}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<p class='error' style='color: #fb7185;'>画像分析エラー: {str(e)}</p>", status_code=500)



@app.get("/api/edinet/history/{code}")
async def get_edinet_history(code: str, current_user: User = Depends(get_current_user)):
    """Get 5-year financial history charts"""
    if not current_user:
         return HTMLResponse(content="<div class='text-red-400'>Login required</div>")
    
    try:

        
        # Fetch history (heavy operation)
        history = get_financial_history(company_code=code, years=5)
        
        if not history:
            return HTMLResponse(content="<div class='text-gray-400 p-4 text-center'>履歴データが見つかりませんでした</div>")
        
        # Prepare data for Chart.js - Cash Flow focused
        years_label = []
        op_cf_data = []      # 営業CF
        inv_cf_data = []     # 投資CF
        fin_cf_data = []     # 財務CF
        net_cf_data = []     # ネットCF
        
        financial_table_rows = ""
        
        # Sort oldest to newest
        for data in history:
            meta = data.get("metadata", {})
            norm = data.get("normalized_data", {})
            
            # Label: use period end date (YYYY-MM)
            period = meta.get("period_end", "")[:7] # YYYY-MM
            years_label.append(period)
            
            # Values (convert to 億円 for easy reading in chart)
            op_cf = norm.get("営業CF", 0)
            op_cf_val = op_cf / 100000000 if isinstance(op_cf, (int, float)) else 0
            op_cf_data.append(round(op_cf_val, 1))
            
            inv_cf = norm.get("投資CF", 0)
            inv_cf_val = inv_cf / 100000000 if isinstance(inv_cf, (int, float)) else 0
            inv_cf_data.append(round(inv_cf_val, 1))
            
            fin_cf = norm.get("財務CF", 0)
            fin_cf_val = fin_cf / 100000000 if isinstance(fin_cf, (int, float)) else 0
            fin_cf_data.append(round(fin_cf_val, 1))
            
            # Net CF = Operating + Investing + Financing
            net_cf_val = op_cf_val + inv_cf_val + fin_cf_val
            net_cf_data.append(round(net_cf_val, 1))
            
            # Add to financial table rows
            formatted = format_financial_data(norm)
            financial_table_rows += f"""
            <tr class="hover:bg-gray-700/30 transition-colors">
                <td class="p-3 text-gray-300 border-b border-gray-700/50">{period}</td>
                <td class="p-3 text-right text-gray-300 border-b border-gray-700/50">{formatted.get('売上高', '-')}</td>
                <td class="p-3 text-right text-emerald-400 border-b border-gray-700/50">{formatted.get('営業利益', '-')}</td>
                <td class="p-3 text-right text-rose-400 border-b border-gray-700/50">{formatted.get('当期純利益', '-')}</td>
                <td class="p-3 text-right text-gray-300 border-b border-gray-700/50">{formatted.get('EPS', '-')}</td>
            </tr>
            """

        chart_id = f"cfChart_{code}_{int(time.time())}"
        
        # Prepare Chart HTML
        chart_html = f"""
            <div class="mt-6 bg-gray-900/50 rounded-xl p-4 border border-gray-700">
                <h4 class="text-lg font-bold text-gray-200 mb-4">キャッシュフロー推移 (5年)</h4>
                
                <div class="h-64 mb-6">
                    <canvas id="{chart_id}"></canvas>
                </div>
                
                <script>
                    (function() {{
                        const ctx = document.getElementById('{chart_id}').getContext('2d');
                        new Chart(ctx, {{
                            type: 'bar',
                            data: {{
                                labels: {years_label},
                                datasets: [
                                    {{
                                        label: '営業CF (億円)',
                                        data: {op_cf_data},
                                        backgroundColor: 'rgba(16, 185, 129, 0.5)',
                                        borderColor: '#10b981',
                                        borderWidth: 1
                                    }},
                                    {{
                                        label: '投資CF (億円)',
                                        data: {inv_cf_data},
                                        backgroundColor: 'rgba(59, 130, 246, 0.5)',
                                        borderColor: '#3b82f6',
                                        borderWidth: 1
                                    }},
                                    {{
                                        label: '財務CF (億円)',
                                        data: {fin_cf_data},
                                        backgroundColor: 'rgba(244, 63, 94, 0.5)',
                                        borderColor: '#f43f5e',
                                        borderWidth: 1
                                    }},
                                    {{
                                        label: 'ネットCF (億円)',
                                        data: {net_cf_data},
                                        type: 'line',
                                        borderColor: '#fbbf24',
                                        borderWidth: 2,
                                        tension: 0.3,
                                        pointBackgroundColor: '#fbbf24'
                                    }}
                                ]
                            }},
                            options: {{
                                responsive: true,
                                maintainAspectRatio: false,
                                interaction: {{
                                    mode: 'index',
                                    intersect: false,
                                }},
                                plugins: {{
                                    legend: {{
                                        labels: {{ color: 'rgba(255, 255, 255, 0.7)' }}
                                    }}
                                }},
                                scales: {{
                                    x: {{
                                        ticks: {{ color: 'rgba(255, 255, 255, 0.5)' }},
                                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}
                                    }},
                                    y: {{
                                        ticks: {{ color: 'rgba(255, 255, 255, 0.5)' }},
                                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}
                                    }}
                                }}
                            }}
                        }});
                    }})();
                </script>
                
                <!-- Button for Financial Ratios Chart -->
                <button hx-get="/api/edinet/ratios/{code}" 
                        hx-target="#edinet-ratios-container" 
                        hx-swap="innerHTML"
                        class="mt-6 w-full py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm font-medium transition-all">
                    <span class="btn-default">財務指標グラフを表示 (ROE・自己資本比率・EPS) (+投資分析サマリー)</span>
                    <span class="btn-loading">⏳ データ取得中...</span>
                </button>
                <div id="edinet-ratios-container" class="mt-4"></div>
            </div>
        """
        
        # Prepare Financial Data Table OOB
        # But OOB swap replaces the whole element. So we should query DB or just use code.
        
        # Simple DB query for name
        db = SessionLocal()
        try:
            company = db.query(Company).filter(Company.ticker == code).first()
            if not company and code.endswith('.T'):
                 company = db.query(Company).filter(Company.ticker == code[:-2]).first()
            company_name = company.name if company else code
        except:
             company_name = code
        finally:
            db.close()
            
        data_table_oob = f"""
        <div id="financial-data-section" class="section" hx-swap-oob="true">
            <h2 style="font-family: 'Outfit', sans-serif; font-size: 1.3rem; margin-bottom: 1.5rem; color: #818cf8; text-align: center;">
                📈 {company_name} 財務推移
            </h2>
            
            <div style="overflow-x: auto;">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr>
                            <th class="p-3 text-gray-400 border-b border-gray-700">決算期</th>
                            <th class="p-3 text-right text-gray-400 border-b border-gray-700">売上高</th>
                            <th class="p-3 text-right text-emerald-400 border-b border-gray-700">営業利益</th>
                            <th class="p-3 text-right text-rose-400 border-b border-gray-700">純利益</th>
                            <th class="p-3 text-right text-gray-400 border-b border-gray-700">EPS</th>
                        </tr>
                    </thead>
                    <tbody>
                        {financial_table_rows}
                    </tbody>
                </table>
            </div>
            <p style="font-size: 0.75rem; color: #64748b; margin-top: 1.5rem; text-align: center;">
                ※ EDINET (有価証券報告書) データおよび XBRL から抽出
            </p>
        </div>
        """
        
        return HTMLResponse(content=chart_html + data_table_oob)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<div class='text-red-400 p-4'>Error: {str(e)}</div>", status_code=500)


@app.get("/api/edinet/ratios/{code}")
async def get_edinet_ratios(code: str, current_user: User = Depends(get_current_user)):
    """Get financial ratios chart AND analysis summary from EDINET"""
    if not current_user:
        return HTMLResponse(content="<div class='text-red-400'>Login required</div>")
    
    try:
        from utils.edinet_enhanced import get_financial_history, format_financial_data
        from utils.growth_analysis import analyze_growth_quality
        import pandas as pd
        import numpy as np
        import time
        import yfinance as yf
        from utils.financial_analysis import analyze_company_performance
        
        # Fetch history (reuse the same function)
        history = get_financial_history(company_code=code, years=5)
        
        if not history:
            return HTMLResponse(content="<div class='text-gray-400 p-4 text-center'>財務指標データが見つかりませんでした</div>")
        
        # --- Prepare Chart Data ---
        years_label = []
        roe_data = []
        equity_ratio_data = []
        eps_data = []
        
        table_rows = ""
        
        for data in history:
            meta = data.get("metadata", {})
            norm = data.get("normalized_data", {})
            
            period = meta.get("period_end", "")[:7]
            years_label.append(period)
            
            # ROE (already percentage from EDINET)
            roe = norm.get("ROE", 0)
            roe_val = roe if isinstance(roe, (int, float)) else 0
            # Handle if stored as decimal (0.15) vs percentage (15)
            if 0 < roe_val < 1:
                roe_val = roe_val * 100
            roe_data.append(round(roe_val, 1))
            
            # Equity Ratio
            eq_ratio = norm.get("自己資本比率", 0)
            eq_ratio_val = eq_ratio if isinstance(eq_ratio, (int, float)) else 0
            if 0 < eq_ratio_val < 1:
                eq_ratio_val = eq_ratio_val * 100
            equity_ratio_data.append(round(eq_ratio_val, 1))
            
            # EPS (円)
            eps = norm.get("EPS", 0)
            eps_val = eps if isinstance(eps, (int, float)) else 0
            eps_data.append(round(eps_val, 1))
            
            formatted = format_financial_data(norm)
            table_rows += f"""
            <tr class="hover:bg-gray-700/30 transition-colors">
                <td class="p-2 text-gray-300 border-b border-gray-700/50">{period}</td>
                <td class="p-2 text-right text-purple-300 border-b border-gray-700/50">{formatted.get('ROE', '-')}</td>
                <td class="p-2 text-right text-cyan-300 border-b border-gray-700/50">{formatted.get('自己資本比率', '-')}</td>
                <td class="p-2 text-right text-orange-300 border-b border-gray-700/50">{formatted.get('EPS', '-')}</td>
            </tr>
            """

        chart_id = f"ratiosChart_{code}_{int(time.time())}"
        
        # --- Prepare Analysis Summary ---
        analysis = analyze_company_performance(history)
        analysis_html = ""
        
        if analysis:
            prof = analysis.get("profitability", {})
            growth = analysis.get("growth_yoy", {})
            safety = analysis.get("safety", {})
            efficiency = analysis.get("efficiency", {})
            
            def get_color(val, threshold=0):
                if val is None: return "text-gray-400"
                return "text-emerald-400" if val >= threshold else "text-rose-400"
            def fmt_pct(val): return f"{val}%" if val is not None else "-"
            def fmt_val(val): return f"{val}" if val is not None else "-"
            
            analysis_html = f"""
                <div class="mt-8 bg-slate-900/80 rounded-xl p-6 border border-indigo-500/30 backdrop-blur-sm shadow-xl animate-fade-in-up">
                    <h4 class="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-cyan-400 mb-6 flex items-center gap-2">
                        <span>📊</span> 投資分析サマリー <span class="text-sm font-normal text-gray-400 ml-2">(最新期: {analysis.get("latest_period", "")})</span>
                    </h4>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                        <!-- Profitability -->
                        <div class="bg-gray-800/50 p-4 rounded-lg border border-gray-700/50">
                            <div class="text-xs uppercase tracking-wider text-purple-400 mb-3 font-bold border-b border-purple-500/20 pb-1">収益性 (Profitability)</div>
                            <div class="flex justify-between mb-2">
                                <span class="text-xs text-gray-400">営業利益率</span>
                                <span class="font-bold {get_color(prof.get('営業利益率'), 10)}">{fmt_pct(prof.get('営業利益率'))}</span>
                            </div>
                            <div class="flex justify-between mb-2">
                                <span class="text-xs text-gray-400">ROE</span>
                                <span class="font-bold {get_color(prof.get('ROE'), 8)}">{fmt_pct(prof.get('ROE'))}</span>
                            </div>
                             <div class="flex justify-between">
                                <span class="text-xs text-gray-400">ROA</span>
                                <span class="font-bold {get_color(prof.get('ROA'), 5)}">{fmt_pct(prof.get('ROA'))}</span>
                            </div>
                        </div>
                        
                        <!-- Growth -->
                        <div class="bg-gray-800/50 p-4 rounded-lg border border-gray-700/50">
                            <div class="text-xs uppercase tracking-wider text-emerald-400 mb-3 font-bold border-b border-emerald-500/20 pb-1">成長性 (Growth YoY)</div>
                            <div class="flex justify-between mb-2">
                                <span class="text-xs text-gray-400">売上高</span>
                                <span class="font-bold {get_color(growth.get('売上高_成長率'), 0)}">{fmt_pct(growth.get('売上高_成長率'))}</span>
                            </div>
                            <div class="flex justify-between mb-2">
                                <span class="text-xs text-gray-400">営業利益</span>
                                <span class="font-bold {get_color(growth.get('営業利益_成長率'), 0)}">{fmt_pct(growth.get('営業利益_成長率'))}</span>
                            </div>
                             <div class="flex justify-between">
                                <span class="text-xs text-gray-400">EPS</span>
                                <span class="font-bold {get_color(growth.get('EPS_成長率'), 0)}">{fmt_pct(growth.get('EPS_成長率'))}</span>
                            </div>
                        </div>
                        
                        <!-- Safety -->
                        <div class="bg-gray-800/50 p-4 rounded-lg border border-gray-700/50">
                            <div class="text-xs uppercase tracking-wider text-cyan-400 mb-3 font-bold border-b border-cyan-500/20 pb-1">安全性 (Safety)</div>
                            <div class="flex justify-between mb-2">
                                <span class="text-xs text-gray-400">自己資本比率</span>
                                <span class="font-bold {get_color(safety.get('自己資本比率'), 40)}">{fmt_pct(safety.get('自己資本比率'))}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-xs text-gray-400">流動比率</span>
                                <span class="font-bold {get_color(safety.get('流動比率'), 100)}">{fmt_pct(safety.get('流動比率'))}</span>
                            </div>
                        </div>
                        
                        <!-- Efficiency -->
                        <div class="bg-gray-800/50 p-4 rounded-lg border border-gray-700/50">
                            <div class="text-xs uppercase tracking-wider text-orange-400 mb-3 font-bold border-b border-orange-500/20 pb-1">効率性 (Efficiency)</div>
                            <div class="flex justify-between">
                                <span class="text-xs text-gray-400">総資産回転率</span>
                                <span class="font-bold text-blue-300">{fmt_val(efficiency.get('総資産回転率'))}回</span>
                            </div>
                        </div>
                    </div>
                </div>
            """

        return HTMLResponse(content=f"""
            <div class="mt-6 bg-gray-900/50 rounded-xl p-4 border border-purple-700/50 transition-all duration-500">
                <h4 class="text-lg font-bold text-gray-200 mb-4 pl-2 border-l-4 border-purple-500">財務指標推移 (5年)</h4>
                
                <div class="h-64 mb-6">
                    <canvas id="{chart_id}"></canvas>
                </div>
                
                <div class="overflow-x-auto mb-6">
                    <table class="w-full text-xs text-left">
                        <thead>
                            <tr>
                                <th class="p-2 text-gray-500">決算期</th>
                                <th class="p-2 text-right text-purple-400">ROE</th>
                                <th class="p-2 text-right text-cyan-400">自己資本比率</th>
                                <th class="p-2 text-right text-orange-400">EPS</th>
                            </tr>
                        </thead>
                        <tbody>
                            {table_rows}
                        </tbody>
                    </table>
                </div>
                
                <script>
                    (function() {{
                        const ctx = document.getElementById('{chart_id}').getContext('2d');
                        new Chart(ctx, {{
                            type: 'line',
                            data: {{
                                labels: {years_label},
                                datasets: [
                                    {{
                                        label: 'ROE (%)',
                                        data: {roe_data},
                                        borderColor: '#a855f7',
                                        backgroundColor: 'rgba(168, 85, 247, 0.1)',
                                        yAxisID: 'y',
                                        tension: 0.3
                                    }},
                                    {{
                                        label: '自己資本比率 (%)',
                                        data: {equity_ratio_data},
                                        borderColor: '#06b6d4',
                                        backgroundColor: 'rgba(6, 182, 212, 0.1)',
                                        yAxisID: 'y',
                                        tension: 0.3
                                    }},
                                    {{
                                        label: 'EPS (円)',
                                        data: {eps_data},
                                        borderColor: '#f97316',
                                        backgroundColor: 'rgba(249, 115, 22, 0.1)',
                                        yAxisID: 'y1',
                                        borderDash: [5, 5],
                                        tension: 0.3
                                    }}
                                ]
                            }},
                            options: {{
                                responsive: true,
                                maintainAspectRatio: false,
                                interaction: {{
                                    mode: 'index',
                                    intersect: false,
                                }},
                                scales: {{
                                    x: {{
                                        ticks: {{ color: 'rgba(255, 255, 255, 0.5)' }},
                                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}
                                    }},
                                    y: {{
                                        type: 'linear',
                                        display: true,
                                        position: 'left',
                                        title: {{ display: true, text: '%' }},
                                        ticks: {{ color: 'rgba(255, 255, 255, 0.5)' }},
                                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}
                                    }},
                                    y1: {{
                                        type: 'linear',
                                        display: true,
                                        position: 'right',
                                        title: {{ display: true, text: '円' }},
                                        ticks: {{ color: 'rgba(255, 255, 255, 0.5)' }},
                                        grid: {{ drawOnChartArea: false }}
                                    }}
                                }}
                            }}
                        }});
                    }})();
                </script>
                
                <!-- Investment Analysis Summary (Auto-Loaded) -->
                {analysis_html}
            </div>
        """)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<div class='text-red-400 p-4'>Error: {str(e)}</div>", status_code=500)


# ==========================================
# Technical Analysis Chart API
# ==========================================

@app.get("/api/chart/technical")
async def get_technical_chart(
    ticker: str = Query(..., description="Stock ticker code (e.g., 7203.T)"),
    period: str = Query("3M", description="Time period: 1M, 3M, 6M, 1Y"),
    current_user: User = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    Get technical analysis chart data for a stock
    Premium feature - requires premium subscription
    """
    try:
        # Debug logging
        if current_user:
            logger.info(f"Technical chart request - User: {current_user.username}, is_admin: {current_user.is_admin}, tier: {get_user_tier(current_user)}")
        else:
            logger.info("Technical chart request - No authenticated user")

        # Check premium access
        if not current_user or not has_feature_access(current_user, "advanced_charts"):
            tier = get_user_tier(current_user) if current_user else "free"
            logger.warning(f"Premium access denied - current_user: {current_user is not None}, tier: {tier}")
            return {
                "error": "premium_required",
                "message": "テクニカル分析チャートはプレミアムプラン限定機能です",
                "current_tier": tier,
                "upgrade_url": "/premium"
            }

        # Calculate number of days to fetch
        days = calculate_period_days(period)

        # Fetch stock data from Yahoo Finance
        # Ensure ticker has .T suffix for Tokyo Stock Exchange
        if not ticker.endswith('.T'):
            ticker = f"{ticker}.T"

        # Download historical data
        stock = yf.Ticker(ticker)
        df = stock.history(period=f"{days}d")

        if df.empty:
            return {
                "error": "no_data",
                "message": "株価データが見つかりませんでした"
            }

        # Calculate all technical indicators
        indicators = calculate_all_indicators(
            df,
            ma_period=25,
            bb_period=20,
            rsi_period=14
        )

        # Format data for Chart.js
        chart_data = format_chartjs_data(df, indicators)

        # Get latest indicator values for display
        latest_values = get_latest_values(indicators)

        # Get current price info
        current_price = float(df['Close'].iloc[-1]) if not df.empty else 0
        prev_price = float(df['Close'].iloc[-2]) if len(df) >= 2 else current_price
        price_change = current_price - prev_price
        price_change_pct = (price_change / prev_price * 100) if prev_price != 0 else 0

        return {
            "success": True,
            "ticker": ticker,
            "period": period,
            "chart_data": chart_data,
            "latest_values": latest_values,
            "current_price": round(current_price, 2),
            "price_change": round(price_change, 2),
            "price_change_pct": round(price_change_pct, 2),
            "data_points": len(df)
        }

    except Exception as e:
        logger.error(f"Technical chart error for {ticker}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "error": "server_error",
            "message": f"エラーが発生しました: {str(e)}"
        }


# ==========================================
# User Profile Endpoints
# ==========================================

@app.get("/profile/edit", response_class=HTMLResponse)
async def profile_edit_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    
    return templates.TemplateResponse("profile_edit.html", {"request": request, "user": current_user, "profile": profile})

@app.post("/api/profile/update", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    display_name: str = Form(None),
    bio: str = Form(None),
    investment_style: str = Form(None),
    icon_emoji: str = Form("👤"),
    twitter_url: str = Form(None),
    is_public: Optional[int] = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    
    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
    
    profile.display_name = display_name if display_name else current_user.username
    profile.bio = bio
    profile.investment_style = investment_style
    profile.icon_emoji = icon_emoji
    profile.twitter_url = twitter_url
    profile.is_public = 1 if is_public else 0
    
    db.commit()
    db.refresh(profile)
    
    return templates.TemplateResponse("profile_edit.html", {
        "request": request, 
        "user": current_user, 
        "profile": profile,
        "message": "プロフィールを更新しました！"
    })

# --- Follow API Endpoints ---

@app.post("/api/follow/{username}", response_class=HTMLResponse)
async def follow_user(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        return HTMLResponse(content="<p style='color:#f43f5e;'>ログインが必要です</p>", status_code=401)
    
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
        
    if target_user.id == current_user.id:
        return HTMLResponse(content="<p style='color:#f43f5e;'>自分自身はフォローできません</p>", status_code=400)
        
    existing_follow = db.query(UserFollow).filter(
        UserFollow.follower_id == current_user.id,
        UserFollow.following_id == target_user.id
    ).first()
    
    if not existing_follow:
        new_follow = UserFollow(follower_id=current_user.id, following_id=target_user.id)
        db.add(new_follow)
        db.commit()
    
    return f"""
        <button hx-delete="/api/follow/{username}" hx-target="this" hx-swap="outerHTML"
            style="background: rgba(244, 63, 94, 0.1); color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.2); padding: 0.6rem 2rem; border-radius: 9999px; font-weight: 600; cursor: pointer; transition: all 0.2s; font-family: 'Inter', sans-serif;">
            フォロー解除
        </button>
    """

@app.delete("/api/follow/{username}", response_class=HTMLResponse)
async def unfollow_user(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        return HTMLResponse(content="<p style='color:#f43f5e;'>ログインが必要です</p>", status_code=401)
        
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
        
    follow = db.query(UserFollow).filter(
        UserFollow.follower_id == current_user.id,
        UserFollow.following_id == target_user.id
    ).first()
    
    if follow:
        db.delete(follow)
        db.commit()
        
    return f"""
        <button hx-post="/api/follow/{username}" hx-target="this" hx-swap="outerHTML"
            style="background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; border: none; padding: 0.6rem 2rem; border-radius: 9999px; font-weight: 600; cursor: pointer; transition: all 0.2s; font-family: 'Inter', sans-serif;">
            フォローする
        </button>
    """

@app.get("/u/{username}", response_class=HTMLResponse)
async def public_profile_page(username: str, request: Request, db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.username == username).first()
    
    if not target_user:
        return HTMLResponse(content="""
            <div style="font-family: sans-serif; text-align: center; padding: 2rem; color: #cbd5e1; background: #0f172a; height: 100vh; display: flex; flex-direction: column; justify-content: center;">
                <h1 style="font-size: 2rem; margin-bottom: 1rem;">User Not Found</h1>
                <p>指定されたユーザーは見つかりませんでした。</p>
                <a href="/" style="color: #818cf8; margin-top: 1rem;">ホームに戻る</a>
            </div>
        """, status_code=404)
    
    profile = db.query(UserProfile).filter(UserProfile.user_id == target_user.id).first()
    
    is_private = False
    if not profile or profile.is_public == 0:
        is_private = True
        
    favorites = []
    if not is_private:
        favorites = db.query(UserFavorite).filter(UserFavorite.user_id == target_user.id).all()
    
    # Follow stats
    follower_count = db.query(UserFollow).filter(UserFollow.following_id == target_user.id).count()
    following_count = db.query(UserFollow).filter(UserFollow.follower_id == target_user.id).count()
    
    # Current user's follow status
    current_user = await get_current_user(request, db)
    is_following = False
    if current_user and current_user.id != target_user.id:
        existing = db.query(UserFollow).filter(
            UserFollow.follower_id == current_user.id,
            UserFollow.following_id == target_user.id
        ).first()
        is_following = existing is not None
        
    return templates.TemplateResponse("profile_public.html", {
        "request": request, 
        "user": target_user, 
        "profile": profile, 
        "favorites": favorites,
        "is_private": is_private,
        "follower_count": follower_count,
        "following_count": following_count,
        "is_following": is_following,
        "current_user": current_user
    })

@app.get("/u/{username}/following", response_class=HTMLResponse)
async def list_following(username: str, request: Request, db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    profile = db.query(UserProfile).filter(UserProfile.user_id == target_user.id).first()
    if not profile or profile.is_public == 0:
        # If private, only allow if same user (but usually follow lists are public if profile is)
        # For simplicity, if profile is private, hide lists.
        raise HTTPException(status_code=403, detail="このユーザーの一覧は非公開です")

    following_relations = db.query(UserFollow).filter(UserFollow.follower_id == target_user.id).all()
    users = [rel.following for rel in following_relations]
    
    return templates.TemplateResponse("follow_list.html", {
        "request": request,
        "users": users,
        "title": f"@{username} がフォロー中",
        "target_username": username,
        "active_tab": "following"
    })

@app.get("/u/{username}/followers", response_class=HTMLResponse)
async def list_followers(username: str, request: Request, db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    profile = db.query(UserProfile).filter(UserProfile.user_id == target_user.id).first()
    if not profile or profile.is_public == 0:
        raise HTTPException(status_code=403, detail="このユーザーの一覧は非公開です")

    follower_relations = db.query(UserFollow).filter(UserFollow.following_id == target_user.id).all()
    users = [rel.follower for rel in follower_relations]
    
    return templates.TemplateResponse("follow_list.html", {
        "request": request,
        "users": users,
        "title": f"@{username} のフォロワー",
        "target_username": username,
        "active_tab": "followers"
    })


# End of file
