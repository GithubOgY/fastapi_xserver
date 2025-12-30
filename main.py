from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Query, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated, Optional
from sqlalchemy.orm import Session
from database import SessionLocal, CompanyFundamental, User, Company, UserFavorite, StockComment, UserProfile, UserFollow
from utils.mail_sender import send_email
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
import time
import os
import json
import yfinance as yf
import pandas as pd
import requests
import urllib.parse
from utils.edinet_enhanced import get_financial_history, format_financial_data, search_company_reports, process_document
from utils.growth_analysis import analyze_growth_quality
from utils.ai_analysis import analyze_stock_with_ai

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

app = FastAPI()

# Mount static files for PWA support
from fastapi.staticfiles import StaticFiles
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

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_hashed_password(password):
    return pwd_context.hash(password)

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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
            company.last_sync_at = now_str
            company.last_sync_error = error_msg
            db.commit()
            db.rollback()

# 初期データの設定
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        # DBスキーマの自動更新 (簡単なマイグレーション)
        from sqlalchemy import text
        try:
            db.execute(text("ALTER TABLE companies ADD COLUMN last_sync_at VARCHAR"))
            db.execute(text("ALTER TABLE companies ADD COLUMN last_sync_error VARCHAR"))
            db.commit()
            logger.info("Database schema updated: added last_sync columns.")
        except Exception:
            db.rollback()

        # is_admin カラムの追加
        try:
            db.execute(text("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0"))
            db.commit()
            logger.info("Database schema updated: added is_admin column.")
        except Exception:
            db.rollback()

        if db.query(User).count() == 0:
            admin_user = User(username=ADMIN_USERNAME, hashed_password=get_hashed_password(ADMIN_PASSWORD), is_admin=1)
            db.add(admin_user)
            db.commit()
        else:
            # 既存のadminユーザーに管理者権限を付与
            admin = db.query(User).filter(User.username == ADMIN_USERNAME).first()
            if admin and not admin.is_admin:
                admin.is_admin = 1
                db.commit()
        
        if db.query(Company).count() == 0:
            initial_companies = {
                "7203.T": "トヨタ自動車",
                "6758.T": "ソニーグループ",
                "9984.T": "ソフトバンクグループ"
            }
            for ticker, name in initial_companies.items():
                db.add(Company(ticker=ticker, name=name))
            db.commit()
    except Exception as e:
        logger.error(f"Startup error: {str(e)}")
    finally:
        db.close()

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
                    db: Session = Depends(get_db), 
                    current_user: User = Depends(get_current_user)):
    
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Read last searched ticker from cookie
    last_ticker = request.cookies.get("last_ticker", "")
    
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
async def login(response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return RedirectResponse(url="/login?error=ユーザー名またはパスワードが違います", status_code=status.HTTP_303_SEE_OTHER)
    
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
    return RedirectResponse(url=f"/register/success?username={username}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/register/success", response_class=HTMLResponse)
async def register_success(request: Request, username: str = ""):
    return templates.TemplateResponse("register_success.html", {
        "request": request,
        "username": username
    })

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
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

@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="自分自身は削除できません")
    
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
    
    return templates.TemplateResponse("account.html", {
        "request": request,
        "user": current_user,
        "comments": user_comments
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
    """Add a stock to user's favorites"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    
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

@app.get("/api/comments/{ticker}", response_class=HTMLResponse)
async def list_comments(
    request: Request,
    ticker: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all comments for a specific ticker and provide a post form"""
    if not current_user:
        return "<p class='text-gray-400 text-center p-4'>掲示板を表示するにはログインが必要です。</p>"
    
    comments = db.query(StockComment).filter(StockComment.ticker == ticker).order_by(StockComment.created_at.desc()).all()
    
    html = f"""
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
        html += f"<p id='no-comments-{ticker}' style='color: #475569; text-align: center; font-size: 0.85rem; padding: 2rem;'>まだ投稿がありません。最初の意見を投稿しましょう！</p>"
    else:
        for comment in comments:
            is_owner = comment.user_id == current_user.id
            delete_btn = f"""
                <button hx-delete="/api/comments/{comment.id}" hx-confirm="この投稿を削除しますか？" hx-target="closest .comment-card" hx-swap="outerHTML"
                    style="background: transparent; border: none; color: #f43f5e; cursor: pointer; font-size: 0.75rem; opacity: 0.6; padding: 0;">
                    削除
                </button>
            """ if is_owner else ""
            
            html += f"""
                <div class="comment-card" style="background: rgba(255,110,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 1rem; position: relative;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                        <a href="/u/{comment.user.username}" style="color: #94a3b8; font-size: 0.8rem; font-weight: 600; text-decoration: none;" onmouseover="this.style.color='#818cf8'" onmouseout="this.style.color='#94a3b8'">@{comment.user.username}</a>
                        <span style="color: #475569; font-size: 0.75rem;">{comment.created_at.strftime('%Y-%m-%d %H:%M')}</span>
                    </div>
                    <div style="color: #f8fafc; font-size: 0.9rem; line-height: 1.5; white-space: pre-wrap;">{comment.content}</div>
                    <div style="text-align: right; margin-top: 0.5rem;">
                        {delete_btn}
                    </div>
                </div>
            """
            
    html += "</div></div>"
    return html

@app.post("/api/comments/{ticker}", response_class=HTMLResponse)
async def post_comment(
    ticker: str,
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new comment for a ticker"""
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
    
    # Return JUST the new comment card. 
    # HTMX swap="afterbegin" on #comments-list-{ticker} will insert this at the top.
    
    html = f"""
        <div class="comment-card" style="background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 12px; padding: 1rem; position: relative; animation: fadeIn 0.5s ease-out;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                <a href="/u/{current_user.username}" style="color: #10b981; font-size: 0.8rem; font-weight: 600; text-decoration: none;" onmouseover="this.style.color='#34d399'" onmouseout="this.style.color='#10b981'">@{current_user.username}</a>
                <span style="color: #475569; font-size: 0.75rem;">Now</span>
            </div>
            <div style="color: #f8fafc; font-size: 0.9rem; line-height: 1.5; white-space: pre-wrap;">{comment.content}</div>
            <div style="text-align: right; margin-top: 0.5rem;">
                 <button hx-delete="/api/comments/{comment.id}" hx-confirm="この投稿を削除しますか？" hx-target="closest .comment-card" hx-swap="outerHTML"
                    style="background: transparent; border: none; color: #f43f5e; cursor: pointer; font-size: 0.75rem; opacity: 0.6; padding: 0;">
                    削除
                </button>
            </div>
            <script>
                // Hide "no comments" message if exists
                var noCommentMsg = document.getElementById('no-comments-{ticker}');
                if(noCommentMsg) noCommentMsg.style.display = 'none';
            </script>
        </div>
    """
    return html

@app.delete("/api/comments/{comment_id}")
async def delete_comment(
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
        
    db.delete(comment)
    db.commit()
    return Response(status_code=status.HTTP_200_OK)



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
                
                # Cash Flow
                op_cf = get_val(cf, "Operating Cash Flow", date) or get_val(cf, "Total Cash From Operating Activities", date)
                inv_cf = get_val(cf, "Investing Cash Flow", date) or get_val(cf, "Total Cashflows From Investing Activities", date)
                fcf = get_val(cf, "Financing Cash Flow", date) or get_val(cf, "Total Cash From Financing Activities", date)
                
                op_cf_data.append(to_oku(op_cf))
                inv_cf_data.append(to_oku(inv_cf))
                fin_cf_data.append(to_oku(fcf))
                net_cf_data.append(to_oku(op_cf + inv_cf + fcf))
                
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
        growth_labels_js = json.dumps(growth_labels)
        growth_rev_actual_js = json.dumps(clean_list(growth_rev_actual))
        growth_rev_target_js = json.dumps(clean_list(growth_rev_target))

        # Generate unique chart IDs
        chart_id1 = f"perf_{code_input}_{int(time.time())}"
        chart_id2 = f"cf_{code_input}_{int(time.time())}"
        chart_id3 = f"growth_{code_input}_{int(time.time())}"
        
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

        # Build clean HTML response with cookie to remember last ticker
        html_content = f"""
            <!-- Stock Info Card -->
            <div style="background: linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.1)); border: 1px solid rgba(99,102,241,0.3); border-radius: 16px; padding: 1.5rem; margin-bottom: 1rem;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem;">
                    <div>
                        <h3 style="font-size: 1.4rem; font-weight: 700; color: #f8fafc; margin: 0;">{name}</h3>
                        <p style="color: #94a3b8; font-size: 0.9rem; margin: 0.25rem 0 0 0;">{symbol}</p>
                        {sector_html}
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 2rem; font-weight: 700; color: #f8fafc;">¥{price:,.0f}</div>
                        <div style="color: {change_color}; font-size: 1rem; font-weight: 600;">
                            {change_sign}{change:,.0f} ({change_sign}{change_pct:.2f}%)
                        </div>
                        {target_price_html}
                        <a href="/edinet?company_name={edinet_name}" 
                           style="display: inline-flex; align-items: center; gap: 0.3rem; margin-top: 0.5rem; background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; text-decoration: none; padding: 0.4rem 0.8rem; border-radius: 8px; font-size: 0.8rem; font-weight: 600; box-shadow: 0 2px 4px rgba(16, 185, 129, 0.2);">
                           <span>📄</span> EDINETで分析
                        </a>
                    </div>
                </div>
                
                {earnings_html}
                
                <!-- Key Metrics Grid -->
                <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.75rem; margin-top: 1.25rem;">
                    <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 10px; text-align: center;">
                        <div style="color: #64748b; font-size: 0.7rem; margin-bottom: 0.25rem;">時価総額</div>
                        <div style="color: #f8fafc; font-weight: 600; font-size: 0.95rem;">{market_cap_str}</div>
                    </div>
                    <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 10px; text-align: center;">
                        <div style="color: #64748b; font-size: 0.7rem; margin-bottom: 0.25rem;">PER</div>
                        <div style="color: #f8fafc; font-weight: 600; font-size: 0.95rem;">{per if isinstance(per, str) else f'{per:.1f}'}</div>
                    </div>
                    <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 10px; text-align: center;">
                        <div style="color: #64748b; font-size: 0.7rem; margin-bottom: 0.25rem;">PBR</div>
                        <div style="color: #f8fafc; font-weight: 600; font-size: 0.95rem;">{pbr if isinstance(pbr, str) else f'{pbr:.2f}'}</div>
                    </div>
                    <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 10px; text-align: center;">
                        <div style="color: #64748b; font-size: 0.7rem; margin-bottom: 0.25rem;">配当利回り</div>
                        <div style="color: #10b981; font-weight: 600; font-size: 0.95rem;">{dividend_str}</div>
                    </div>
                    <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 10px; text-align: center;">
                        <div style="color: #64748b; font-size: 0.7rem; margin-bottom: 0.25rem;">ROE</div>
                        <div style="color: #818cf8; font-weight: 600; font-size: 0.95rem;">{roe_str}</div>
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
                <h2 style="font-family: 'Outfit', sans-serif; font-size: 1.2rem; margin-bottom: 1rem; color: #818cf8; text-align: center;">
                    📊 財務パフォーマンス
                </h2>
                
                <!-- Two Column Charts (responsive) -->
                <style>
                    .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
                    @media (max-width: 768px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}
                </style>
                <div class="chart-grid">
                    <!-- Revenue/Profit Chart -->
                    <div style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1rem; max-width: 100%; overflow: hidden;">
                        <h4 style="color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.75rem 0; text-align: center;">売上 / 営業利益</h4>
                        <div style="height: 220px; position: relative; width: 100%;">
                            <canvas id="{chart_id1}"></canvas>
                        </div>
                    </div>
                    
                    <!-- Cash Flow Chart -->
                    <div style="background: rgba(0,0,0,0.2); border-radius: 12px; padding: 1rem; max-width: 100%; overflow: hidden;">
                        <h4 style="color: #94a3b8; font-size: 0.85rem; margin: 0 0 0.75rem 0; text-align: center;">キャッシュフロー</h4>
                        <div style="height: 220px; position: relative; width: 100%;">
                            <canvas id="{chart_id2}"></canvas>
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
                            scales: {{
                                y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, title: {{ display: true, text: '億円', color: '#64748b', font: {{ size: 10 }} }} }},
                                y1: {{ position: 'right', grid: {{ display: false }}, ticks: {{ color: '#f59e0b', font: {{ size: 10 }} }}, min: 0 }},
                                x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }} }}
                            }},
                            plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }} }}
                        }}
                    }});
                    
                    // Cash Flow Chart
                    new Chart(document.getElementById('{chart_id2}').getContext('2d'), {{
                        type: 'bar',
                        data: {{
                            labels: {years_label_js},
                            datasets: [
                                {{ label: '営業CF', data: {op_cf_data_js}, backgroundColor: 'rgba(16,185,129,0.7)', borderColor: '#10b981', borderWidth: 1 }},
                                {{ label: '投資CF', data: {inv_cf_data_js}, backgroundColor: 'rgba(244,63,94,0.7)', borderColor: '#f43f5e', borderWidth: 1 }},
                                {{ label: '財務CF', data: {fin_cf_data_js}, backgroundColor: 'rgba(59,130,246,0.7)', borderColor: '#3b82f6', borderWidth: 1 }},
                                {{ label: 'ネットCF', data: {net_cf_data_js}, type: 'line', borderColor: '#f59e0b', borderWidth: 2, tension: 0.3, pointRadius: 4 }}
                            ]
                        }},
                        options: {{
                            responsive: true, maintainAspectRatio: false,
                            scales: {{
                                y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, title: {{ display: true, text: '億円', color: '#64748b', font: {{ size: 10 }} }} }},
                                x: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b', font: {{ size: 10 }} }} }}
                            }},
                            plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }} }}
                        }}
                    }});
                }})();
                </script>
            </div>

            <!-- Growth & Quality Analysis (OOB Swap) -->
            <div id="growth-analysis-section" class="section" hx-swap-oob="true" style="margin-top: 1rem;">
                <h2 style="font-family: 'Outfit', sans-serif; font-size: 1.2rem; margin-bottom: 1rem; color: #10b981; text-align: center;">
                    🚀 成長性・クオリティ分析 (年率10%目標)
                </h2>
                
                <!-- Growth Charts & Scorecards -->
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
                                {'✅ 10%目標達成' if growth_analysis['is_high_growth'] else '基準未達 / データ不足'}
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

                <script>
                (function() {{
                    const ctx = document.getElementById('{chart_id3}').getContext('2d');
                    new Chart(ctx, {{
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
                                    label: '10%成長目標ライン',
                                    data: {growth_rev_target_js},
                                    type: 'line',
                                    borderColor: '#fbbf24',
                                    borderDash: [5, 5],
                                    borderWidth: 2,
                                    fill: false,
                                    pointRadius: 0
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

            <!-- News Section (OOB Swap) -->
            <div id="news-section" class="section" hx-swap-oob="true" style="margin-top: 2rem;">
                <div hx-get="/api/news/{code_only}?name={urllib.parse.quote(name)}" hx-trigger="load delay:500ms" hx-swap="innerHTML">
                    <div class="flex items-center justify-center p-8 space-x-3 text-gray-400">
                        <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-green-400"></div>
                        <span class="text-sm font-medium">最新ニュースを取得中...</span>
                    </div>
                </div>
            </div>

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
            <div id="discussion-section" hx-swap-oob="true" style="display: block; margin-top: 1rem;">
                <div hx-get="/api/comments/{code_input}" hx-trigger="load">
                    <p style="color: #64748b; text-align: center; font-size: 0.85rem; padding: 2rem;">
                        掲示板を読み込み中...
                    </p>
                </div>
            </div>

            <!-- OOB Swap: Update Register Button in Search Form -->
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

@app.post("/api/edinet/search")
async def search_edinet_company(
    company_name: str = Form(...),
    current_user: User = Depends(get_current_user)
):
    """Search company financial data from EDINET (Latest)"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:

        
        # Search for documents
        docs = search_company_reports(company_name=company_name, doc_type="120", days_back=365)
        
        if not docs:
            # Try quarterly report
            docs = search_company_reports(company_name=company_name, doc_type="140", days_back=180)
        
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
        
        # Qualitative Information Sections with Copy Button
        sections_html = ""
        # Display order: Business overview -> Strategy -> Analysis -> Risks -> Challenges -> Operations
        text_keys = [
            "事業の内容",
            "経営方針・経営戦略", 
            "経営者による分析",
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
                <details class="mb-3 bg-gray-900/30 rounded-lg border border-gray-700/50 overflow-hidden">
                    <summary class="cursor-pointer p-4 bg-gray-800/50 hover:bg-gray-700/50 transition-colors font-medium text-gray-200 list-none flex items-center justify-between">
                        <span>{key}</span>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <button 
                                id="{copy_btn_id}"
                                onclick="event.stopPropagation(); event.preventDefault(); copyToClipboard('{section_id}', '{copy_btn_id}');"
                                class="p-0 text-gray-500 hover:text-indigo-400 transition-colors"
                                title="クリップボードにコピー">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                                </svg>
                            </button>
                            <span class="text-gray-500 text-sm">クリックして展開</span>
                        </div>
                    </summary>
                    <div id="{section_id}" class="p-6 text-base text-gray-200 leading-loose border-t border-gray-700/50 bg-gray-900/50" style="white-space: pre-wrap; line-height: 2;">
                        {content}
                    </div>
                </details>
                """

        history_btn = ""  # Disabled - removed the financial chart button
        
        # Website link HTML
        website_html = ""
        if website_url:
            website_html = f'<a href="{website_url}" target="_blank" rel="noopener" class="text-blue-400 hover:text-blue-300 underline text-sm">企業サイト</a>'

        # AI Analysis Button
        ai_btn = ""
        if sec_code:
            code_only = sec_code[:4]
            ai_btn = f"""
            <div style="margin-top: 2rem; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 1.5rem;">
                <h4 style="font-size: 1.2rem; font-weight: bold; text-align: center; margin-bottom: 1rem; background: linear-gradient(to right, #c084fc, #ec4899); -webkit-background-clip: text; -webkit-text-fill-color: transparent; display: inline-block; width: 100%;">
                    🤖 AIアナリスト・レポート
                </h4>
                <div id="ai-analysis-container">
                    <button id="ai-gen-btn-{code_only}" 
                        style="width: 100%; padding: 1rem; background: linear-gradient(135deg, #9333ea, #db2777); color: white; border: none; border-radius: 12px; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 0.5rem; transition: all 0.2s;"
                        hx-post="/api/ai/analyze"
                        hx-target="#ai-analysis-content"
                        hx-vals='{{"ticker_code": "{code_only}"}}'
                        hx-on:htmx:before-request="this.querySelector('span').innerText = '🤖 AI分析を生成中... (30~60秒)'; this.disabled = true; this.style.opacity = '0.8';"
                        hx-on:htmx:after-request="this.querySelector('span').innerText = 'AIによる詳細分析を生成 (Gemini 2.0 Flash)'; this.disabled = false; this.style.opacity = '1';">
                        <span>AIによる詳細分析を生成 (Gemini 2.0 Flash)</span>
                    </button>
                    <style>
                        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
                        #ai-gen-btn-{code_only}:disabled {{ cursor: wait; }}
                    </style>
                    <div id="ai-analysis-content" style="margin-top: 1rem; color: #e2e8f0; line-height: 1.7; font-size: 0.95rem;"></div>
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
                        <div class="flex items-center gap-2 mt-2 text-sm text-gray-400">
                            <span class="bg-gray-900/50 px-2 py-1 rounded">{metadata.get('document_type')}</span>
                            <span class="text-xs text-gray-500">提出: {metadata.get('submit_date')}</span>
                            {'<span class="text-xs text-green-400 bg-green-900/30 px-2 py-1 rounded">⚡ キャッシュ</span>' if metadata.get('from_cache') else ''}
                        </div>
                    </div>
                </div>
                
                <!-- Key Financials Summary -->
                <div class="bg-gray-900/50 p-4 rounded-lg border border-gray-700/50 mb-6 font-mono text-sm">
                    <div class="grid grid-cols-2 gap-2">
                        <div class="text-gray-300">売上高　<span class="text-gray-100">{formatted_normalized.get("売上高", "-")}</span></div>
                        <div class="text-gray-300">営業利益　<span class="text-emerald-400">{formatted_normalized.get("営業利益", "-")}</span></div>
                        <div class="text-gray-300">当期純利益　<span class="text-blue-400">{formatted_normalized.get("当期純利益", "-")}</span></div>
                        <div class="text-gray-300">ROE　<span class="text-purple-400">{formatted_normalized.get("ROE", "-")}</span></div>
                        <div class="text-gray-300">ROA　<span class="text-purple-400">{formatted_normalized.get("ROA", "-")}</span></div>
                        <div class="text-gray-300">自己資本比率　<span class="text-yellow-400">{formatted_normalized.get("自己資本比率", "-")}</span></div>
                    </div>
                </div>
                
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
    current_user: User = Depends(get_current_user)
):
    """AI Analysis Endpoint using Gemini 2.0 Flash"""
    if not current_user:
        return "<div class='text-red-400'>エラー: ログインが必要です</div>"

    try:
        clean_code = ticker_code.replace(".T", "")
        
        # Context data preparation
        financial_context = {}
        company_name = f"Code: {clean_code}"
        
        # Fetch latest financial data for context
        history = get_financial_history(company_code=clean_code, years=1)
        if history and len(history) > 0:
            data = history[0]
            financial_context = data.get("normalized_data", {})
            meta = data.get("metadata", {})
            company_name = meta.get("company_name", company_name)
        
        # Execute Analysis (returns HTML)
        return analyze_stock_with_ai(clean_code, financial_context, company_name)
        
    except Exception as e:
        logger.error(f"AI Analysis error: {e}")
        import traceback
        traceback.print_exc()
        return f"<div class='text-red-400'>AI分析中にエラーが発生しました: {str(e)}</div>"



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
