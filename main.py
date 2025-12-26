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
def sync_stock_data(db: Session):
    tickers = ["7203.T", "6758.T", "9984.T"]
    logger.info(f"Starting sync for tickers: {tickers}")
    
    for ticker_symbol in tickers:
        try:
            logger.info(f"Refreshing data for {ticker_symbol}...")
            ticker = yf.Ticker(ticker_symbol)
            
            # 銘柄情報の取得 (失敗しても続行)
            try:
                info = ticker.info
                company_name = info.get('longName', info.get('shortName', ticker_symbol))
                company = db.query(Company).filter(Company.ticker == ticker_symbol).first()
                if company:
                    company.name = company_name
                else:
                    db.add(Company(ticker=ticker_symbol, name=company_name))
                db.commit()
            except Exception as info_e:
                logger.warning(f"Could not fetch info for {ticker_symbol}: {str(info_e)}")
            
            # 財務データの取得
            financials = ticker.financials
            if financials is None or financials.empty:
                logger.warning(f"No financial data returned for {ticker_symbol}")
                continue
            
            df = financials.T
            for date, row in df.iterrows():
                try:
                    year = date.year
                    logger.info(f"Processing {ticker_symbol} for year {year}")
                    
                    # データの抽出 (yfinanceのキー名揺れに対応)
                    revenue_raw = row.get('Total Revenue') or row.get('TotalRevenue') or 0
                    op_income_raw = row.get('Operating Income') or row.get('OperatingIncome') or 0
                    net_income_raw = row.get('Net Income Common Stockholders') or row.get('NetIncomeCommonStockholders') or row.get('Net Income') or 0
                    eps_raw = row.get('Basic EPS') or row.get('BasicEPS') or 0
                    
                    # 単位を億円に変換
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
                    logger.error(f"Error processing row for {ticker_symbol} {date}: {str(row_e)}")
                    db.rollback()
            
            logger.info(f"Successfully synced {ticker_symbol}")
            
        except Exception as e:
            logger.error(f"Major error syncing {ticker_symbol}: {str(e)}")
            db.rollback()

# 初期データの設定
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        # ユーザー
        if db.query(User).count() == 0:
            admin_user = User(username=ADMIN_USERNAME, hashed_password=get_hashed_password(ADMIN_PASSWORD))
            db.add(admin_user)
            db.commit()
        
        # 銘柄マスタ基本
        if db.query(Company).count() == 0:
            initial_companies = {
                "7203.T": "トヨタ自動車",
                "6758.T": "ソニーグループ",
                "9984.T": "ソフトバンクグループ"
            }
            for ticker, name in initial_companies.items():
                db.add(Company(ticker=ticker, name=name))
            db.commit()
        
        # 初回データ取得 (PostgreSQL移行後はここがトリガーされる)
        if db.query(CompanyFundamental).count() == 0:
            logger.info("No data found in DB, starting initial sync...")
            sync_stock_data(db)
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
            "ticker_name": f"{ticker} {ticker_display}",
            "current_ticker": ticker,
            "ticker_list": ticker_list,
            "user": current_user
        }
    )

@app.post("/admin/sync")
async def manual_sync(ticker: str = "7203.T", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    sync_stock_data(db)
    return RedirectResponse(url=f"/?ticker={ticker}", status_code=status.HTTP_303_SEE_OTHER)

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
async def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        return HTMLResponse(content="<p style='color:red;'>このユーザー名は既に使用されています</p>", status_code=400)
    
    new_user = User(username=username, hashed_password=get_hashed_password(password))
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response

@app.post("/echo")
async def echo(message: Annotated[str, Form()]):
    if not message:
        return '<p class="echo-result">何か入力してください！</p>'
    return f'<p class="echo-result">サーバーからの返信: <strong>{message}</strong></p>'
