from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated, Optional
from sqlalchemy.orm import Session
from database import SessionLocal, CompanyFundamental, User
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import logging
import time
import os

# --- Logging Configuration ---
LOG_DIR = "logs"
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

# セキュリティ設定
SECRET_KEY = "your-secret-key-keep-it-secret"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 初期データの設定
TICKER_NAMES = {
    "7203.T": "トヨタ自動車",
    "6758.T": "ソニーグループ",
    "9984.T": "ソフトバンクグループ"
}

@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    if db.query(User).count() == 0:
        admin_user = User(username="admin", hashed_password=get_hashed_password("password"))
        db.add(admin_user)
        db.commit()
    
    # 各銘柄ごとに、データがなければ投入する
    tickers_to_seed = ["7203.T", "6758.T", "9984.T"]
    for ticker in tickers_to_seed:
        if db.query(CompanyFundamental).filter(CompanyFundamental.ticker == ticker).count() == 0:
            if ticker == "7203.T":
                data = [
                    CompanyFundamental(ticker="7203.T", year=2024, revenue=450953.25, operating_income=53529.34, net_income=49449.33, eps=365.94),
                    CompanyFundamental(ticker="7203.T", year=2025, revenue=480367.04, operating_income=47955.86, net_income=47650.86, eps=359.56),
                ]
            elif ticker == "6758.T":
                data = [
                    CompanyFundamental(ticker="6758.T", year=2024, revenue=130235.00, operating_income=12082.00, net_income=9706.00, eps=785.12),
                    CompanyFundamental(ticker="6758.T", year=2025, revenue=140000.00, operating_income=13000.00, net_income=10500.00, eps=850.45),
                ]
            elif ticker == "9984.T":
                data = [
                    CompanyFundamental(ticker="9984.T", year=2024, revenue=67565.00, operating_income=8732.00, net_income=4521.00, eps=312.44),
                    CompanyFundamental(ticker="9984.T", year=2025, revenue=71000.00, operating_income=9500.00, net_income=5200.00, eps=358.12),
                ]
            db.add_all(data)
            db.commit()
    db.close()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, 
                    ticker: str = Query("7203.T"),
                    db: Session = Depends(get_db), 
                    current_user: User = Depends(get_current_user)):
    
    fundamentals = db.query(CompanyFundamental).filter(CompanyFundamental.ticker == ticker).all()
    ticker_display = TICKER_NAMES.get(ticker, ticker)
    
    # 全銘柄リスト（検索ドロップダウン用）
    all_tickers = db.query(CompanyFundamental.ticker).distinct().all()
    ticker_list = [{"code": t[0], "name": TICKER_NAMES.get(t[0], t[0])} for t in all_tickers]

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
