from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated, Optional
from sqlalchemy.orm import Session
from database import SessionLocal, CompanyFundamental, User, Company, UserFavorite
from utils.email import send_email
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
import time
import os
import yfinance as yf
import pandas as pd
import requests

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

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, 
                    ticker: str = Query("7203.T"),
                    db: Session = Depends(get_db), 
                    current_user: User = Depends(get_current_user)):
    
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
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
            "favorite_companies": favorite_companies
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
    
    return templates.TemplateResponse("account.html", {
        "request": request,
        "user": current_user
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

@app.post("/echo")
async def echo(message: Annotated[str, Form()]):
    if not message:
        return '<p class="echo-result">Please enter something!</p>'
    return f'<p class="echo-result">Server response: <strong>{message}</strong></p>'

# --- Favorites API ---

@app.post("/api/favorites/add")
async def add_favorite(ticker: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Login required")
    
    # Check if already favorited
    existing = db.query(UserFavorite).filter(
        UserFavorite.user_id == current_user.id,
        UserFavorite.ticker == ticker
    ).first()
    
    if not existing:
        favorite = UserFavorite(user_id=current_user.id, ticker=ticker)
        db.add(favorite)
        db.commit()
    
    return RedirectResponse(url=f"/dashboard?ticker={ticker}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/api/favorites/remove")
async def remove_favorite(ticker: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Login required")
    
    favorite = db.query(UserFavorite).filter(
        UserFavorite.user_id == current_user.id,
        UserFavorite.ticker == ticker
    ).first()
    
    if favorite:
        db.delete(favorite)
        db.commit()
    
    return RedirectResponse(url=f"/dashboard?ticker={ticker}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/api/favorites")
async def get_favorites(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        return []
    
    favorites = db.query(UserFavorite).filter(UserFavorite.user_id == current_user.id).all()
    return [f.ticker for f in favorites]

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


# --- EDINET API Endpoint ---
@app.post("/api/edinet/search")
async def search_edinet_company(
    company_name: str = Form(...),
    current_user: User = Depends(get_current_user)
):
    """Search company financial data from EDINET (Latest)"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        from utils.edinet_enhanced import search_company_reports, process_document, format_financial_data
        
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
        formatted_normalized = format_financial_data(normalized)
        
        # Qualitative Information Sections
        sections_html = ""
        text_keys = ["経営者による分析", "対処すべき課題", "事業等のリスク", "研究開発活動"]
        
        for key in text_keys:
            content = text_data.get(key)
            if content:
                # Truncate for preview (first 300 chars)
                preview = content[:300] + "..." if len(content) > 300 else content
                
                # HTML for expandable section - NO SVG icons, simple text only
                sections_html += f"""
                <details class="mb-3 bg-gray-900/30 rounded-lg border border-gray-700/50 overflow-hidden">
                    <summary class="cursor-pointer p-4 bg-gray-800/50 hover:bg-gray-700/50 transition-colors font-medium text-gray-200 list-none flex items-center justify-between">
                        <span>{key}</span>
                        <span class="text-gray-500 text-sm">クリックして展開</span>
                    </summary>
                    <div class="p-6 text-base text-gray-200 leading-loose border-t border-gray-700/50 bg-gray-900/50" style="white-space: pre-wrap; line-height: 2;">
                        {content}
                    </div>
                </details>
                """

        history_btn = ""
        if sec_code:
            code_only = sec_code[:4] # First 4 digits
            history_btn = f"""
            <button hx-get="/api/edinet/history/{code_only}" 
                    hx-target="#edinet-history-container" 
                    hx-swap="innerHTML"
                    hx-disabled-elt="this"
                    class="mt-6 w-full py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 disabled:cursor-wait text-white rounded-lg text-sm font-medium transition-all">
                <span class="htmx-indicator-hide">直近の財務推移グラフを表示</span>
                <span class="htmx-indicator-show hidden">⏳ データ取得中... (数十秒かかる場合があります)</span>
            </button>
            <style>
                button[disabled] .htmx-indicator-hide {{ display: none; }}
                button[disabled] .htmx-indicator-show {{ display: inline !important; }}
            </style>
            <div id="edinet-history-container" class="mt-4"></div>
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
                        </div>
                        <div class="flex items-center gap-2 mt-2 text-sm text-gray-400">
                            <span class="bg-gray-900/50 px-2 py-1 rounded">{metadata.get('document_type')}</span>
                            <span class="text-xs text-gray-500">提出: {metadata.get('submit_date')}</span>
                        </div>
                    </div>
                </div>
                
                <!-- Key Financials Summary - Inline format -->
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


@app.get("/api/edinet/history/{code}")
async def get_edinet_history(code: str, current_user: User = Depends(get_current_user)):
    """Get 5-year financial history charts"""
    if not current_user:
         return HTMLResponse(content="<div class='text-red-400'>Login required</div>")
    
    try:
        from utils.edinet_enhanced import get_financial_history, format_financial_data
        
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
        
        table_rows = ""
        
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
            
            # Add to table
            formatted = format_financial_data(norm)
            table_rows += f"""
            <tr class="hover:bg-gray-700/30 transition-colors">
                <td class="p-2 text-gray-300 border-b border-gray-700/50">{period}</td>
                <td class="p-2 text-right text-blue-300 border-b border-gray-700/50">{formatted.get('営業CF', '-')}</td>
                <td class="p-2 text-right text-red-300 border-b border-gray-700/50">{formatted.get('投資CF', '-')}</td>
                <td class="p-2 text-right text-yellow-300 border-b border-gray-700/50">{formatted.get('財務CF', '-')}</td>
                <td class="p-2 text-right text-green-300 border-b border-gray-700/50">{round(net_cf_val, 1)}億円</td>
            </tr>
            """

        # Generate unique chart ID
        chart_id = f"historyChart_{code}_{int(time.time())}"
        
        return HTMLResponse(content=f"""
            <div class="mt-6 bg-gray-900/50 rounded-xl p-4 border border-gray-700">
                <h4 class="text-lg font-bold text-gray-200 mb-4">キャッシュフロー推移 (5年)</h4>
                
                <div class="h-64 mb-6">
                    <canvas id="{chart_id}"></canvas>
                </div>
                
                <div class="overflow-x-auto">
                    <table class="w-full text-xs text-left">
                        <thead>
                            <tr>
                                <th class="p-2 text-gray-500">決算期</th>
                                <th class="p-2 text-right text-blue-400">営業CF</th>
                                <th class="p-2 text-right text-red-400">投資CF</th>
                                <th class="p-2 text-right text-yellow-400">財務CF</th>
                                <th class="p-2 text-right text-green-400">ネットCF</th>
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
                            type: 'bar',
                            data: {{
                                labels: {years_label},
                                datasets: [
                                    {{
                                        label: '営業CF (億円)',
                                        data: {op_cf_data},
                                        backgroundColor: 'rgba(59, 130, 246, 0.7)',
                                        borderColor: 'rgba(59, 130, 246, 1)',
                                        borderWidth: 1,
                                    }},
                                    {{
                                        label: '投資CF (億円)',
                                        data: {inv_cf_data},
                                        backgroundColor: 'rgba(239, 68, 68, 0.7)',
                                        borderColor: 'rgba(239, 68, 68, 1)',
                                        borderWidth: 1,
                                    }},
                                    {{
                                        label: '財務CF (億円)',
                                        data: {fin_cf_data},
                                        backgroundColor: 'rgba(234, 179, 8, 0.7)',
                                        borderColor: 'rgba(234, 179, 8, 1)',
                                        borderWidth: 1,
                                    }},
                                    {{
                                        label: 'ネットCF (億円)',
                                        data: {net_cf_data},
                                        type: 'line',
                                        borderColor: 'rgba(34, 197, 94, 1)',
                                        backgroundColor: 'rgba(34, 197, 94, 0.2)',
                                        borderWidth: 3,
                                        fill: false,
                                        tension: 0.1,
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
            </div>
        """)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTMLResponse(content=f"<div class='text-red-400 p-4'>Error: {str(e)}</div>", status_code=500)
