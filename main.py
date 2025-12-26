from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated, Optional
from sqlalchemy.orm import Session
from database import SessionLocal, CompanyFundamental, User, Company
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
async def read_root(request: Request, 
                    ticker: str = Query("7203.T"),
                    db: Session = Depends(get_db), 
                    current_user: User = Depends(get_current_user)):
    
    fundamentals = db.query(CompanyFundamental).filter(CompanyFundamental.ticker == ticker).order_by(CompanyFundamental.year.desc()).all()
    company = db.query(Company).filter(Company.ticker == ticker).first()
    ticker_display = company.name if company else ticker
    
    all_companies = db.query(Company).all()
    ticker_list = [{"code": c.ticker, "name": c.name} for c in all_companies]

    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "fundamentals": fundamentals,
            "company": company,
            "ticker_name": f"{ticker} {ticker_display}",
            "current_ticker": ticker,
            "ticker_list": ticker_list,
            "user": current_user
        }
    )

@app.post("/admin/sync")
async def manual_sync(request: Request, ticker: str = "7203.T", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    sync_stock_data(db, target_ticker=ticker)
    
    # HTMXリクエストの場合は、ページ全体を再描画するようにリダイレクト先を返す
    # (hx-target="body" hx-swap="outerHTML" を使っているため、read_rootを呼び出す)
    return await read_root(request, ticker=ticker, db=db, current_user=current_user)

# --- Auth Endpoints ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return HTMLResponse(content="<p style='color:red;'>ユーザー名またはパスワードが違います</p>", status_code=401)
    
    access_token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
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
        return '<p class="echo-result">何か入力してください！</p>'
    return f'<p class="echo-result">サーバーからの返信: <strong>{message}</strong></p>'
