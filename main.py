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
        website_url = result.get("website_url")
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
            <style>
                .btn-loading {{ display: none; }}
                .htmx-request .btn-default {{ display: none; }}
                .htmx-request .btn-loading {{ display: inline; }}
            </style>
            <button hx-get="/api/edinet/history/{code_only}" 
                    hx-target="#edinet-history-container" 
                    hx-swap="innerHTML"
                    class="mt-10 w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-all">
                <span class="btn-default">直近の財務推移グラフを表示</span>
                <span class="btn-loading">⏳ データ取得中... (数十秒かかる場合があります)</span>
            </button>
            <div id="edinet-history-container" class="mt-4"></div>
            """
        
        # Website link HTML
        website_html = ""
        if website_url:
            website_html = f'<a href="{website_url}" target="_blank" rel="noopener" class="text-blue-400 hover:text-blue-300 underline text-sm">企業サイト</a>'
        
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


@app.post("/api/yahoo-finance/lookup")
async def lookup_yahoo_finance(
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
    else:
        symbol = code_input
    
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
        dividend_yield = info.get("dividendYield")
        dividend_str = f"{dividend_yield * 100:.2f}%" if dividend_yield else "-"
        
        roe = info.get("returnOnEquity")
        roe_str = f"{roe * 100:.1f}%" if roe else "-"
        
        # Color for price change
        change_color = "#10b981" if change >= 0 else "#f43f5e"
        change_sign = "+" if change >= 0 else ""
        
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
        
        return HTMLResponse(content=f"""
            <div style="background: rgba(0, 0, 0, 0.2); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 1.5rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 1rem;">
                    <div>
                        <div style="font-size: 1.2rem; font-weight: bold; color: #f8fafc;">{name}</div>
                        <div style="font-size: 0.85rem; color: #94a3b8;">{symbol}</div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 1rem;">
                        <div style="text-align: right;">
                            <div style="font-size: 1.5rem; font-weight: bold; color: #f8fafc;">¥{price:,.0f}</div>
                            <div style="color: {change_color}; font-size: 0.9rem;">{change_sign}{change:,.0f} ({change_sign}{change_pct:.2f}%)</div>
                        </div>
                        {fav_button}
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 0.75rem; font-size: 0.85rem;">
                    <div style="background: rgba(99, 102, 241, 0.1); padding: 0.75rem; border-radius: 8px; text-align: center;">
                        <div style="color: #94a3b8; font-size: 0.75rem;">時価総額</div>
                        <div style="color: #f8fafc; font-weight: 600;">{market_cap_str}</div>
                    </div>
                    <div style="background: rgba(99, 102, 241, 0.1); padding: 0.75rem; border-radius: 8px; text-align: center;">
                        <div style="color: #94a3b8; font-size: 0.75rem;">PER</div>
                        <div style="color: #f8fafc; font-weight: 600;">{per if isinstance(per, str) else f'{per:.1f}'}</div>
                    </div>
                    <div style="background: rgba(99, 102, 241, 0.1); padding: 0.75rem; border-radius: 8px; text-align: center;">
                        <div style="color: #94a3b8; font-size: 0.75rem;">PBR</div>
                        <div style="color: #f8fafc; font-weight: 600;">{pbr if isinstance(pbr, str) else f'{pbr:.2f}'}</div>
                    </div>
                    <div style="background: rgba(99, 102, 241, 0.1); padding: 0.75rem; border-radius: 8px; text-align: center;">
                        <div style="color: #94a3b8; font-size: 0.75rem;">配当利回り</div>
                        <div style="color: #f8fafc; font-weight: 600;">{dividend_str}</div>
                    </div>
                    <div style="background: rgba(99, 102, 241, 0.1); padding: 0.75rem; border-radius: 8px; text-align: center;">
                        <div style="color: #94a3b8; font-size: 0.75rem;">ROE</div>
                        <div style="color: #f8fafc; font-weight: 600;">{roe_str}</div>
                    </div>
                </div>
            
            <!-- Simple action to load details if needed via button, not auto -->
            <div class="mt-4 text-center">
                <button 
                    hx-get="/api/edinet/history/{symbol}"
                    hx-target="#chart-container"
                    hx-swap="innerHTML"
                    onclick="document.getElementById('chart-section').scrollIntoView({{behavior: 'smooth'}})"
                    class="py-2 px-6 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg shadow transition-colors flex items-center justify-center gap-2 mx-auto">
                    <span>📊 詳細分析・チャートを表示 (EDINET)</span>
                    <span class="htmx-indicator">⏳</span>
                </button>
                <p class="text-xs text-gray-400 mt-2">※ 公式財務データを取得してグラフを描画します</p>
            </div>
        </div>
        """)
        
    except Exception as e:
        logger.error(f"Yahoo Finance lookup error for {code}: {e}")
        return HTMLResponse(content=f"""
            <div style="color: #fb7185; padding: 1rem; text-align: center; background: rgba(244, 63, 94, 0.1); border-radius: 8px;">
                ❌ データの取得に失敗しました: {str(e)}
            </div>
        """)


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
