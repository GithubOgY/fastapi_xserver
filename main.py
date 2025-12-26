from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated, Optional
from sqlalchemy.orm import Session
from database import SessionLocal, CompanyFundamental, User
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta

# セキュリティ設定
SECRET_KEY = "your-secret-key-keep-it-secret" # 練習用なので直書き
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

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

# 初期データ
@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    # ユーザー追加 (admin / password)
    if db.query(User).count() == 0:
        admin_user = User(username="admin", hashed_password=get_hashed_password("password"))
        db.add(admin_user)
        db.commit()
    
    # 財務データ追加
    if db.query(CompanyFundamental).count() == 0:
        data = [
            CompanyFundamental(ticker="7203.T", year=2024, revenue=450953.25, operating_income=53529.34, net_income=49449.33, eps=365.94),
            CompanyFundamental(ticker="7203.T", year=2025, revenue=480367.04, operating_income=47955.86, net_income=47650.86, eps=359.56)
        ]
        db.add_all(data)
        db.commit()
    db.close()

# 状態管理 (カウンター)
state = {"counter": 0}

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    fundamentals = db.query(CompanyFundamental).filter(CompanyFundamental.ticker == "7203.T").all()
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "counter": state["counter"],
            "fundamentals": fundamentals,
            "ticker_name": "7203.T トヨタ自動車",
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

@app.post("/increment")
async def increment(current_user: User = Depends(get_current_user)):
    if not current_user:
        return HTMLResponse(content="<script>alert('ログインが必要です');</script>")
    state["counter"] += 1
    return f'<span id="counter-value" class="counter-animate">{state["counter"]}</span>'

@app.post("/echo")
async def echo(message: Annotated[str, Form()]):
    if not message:
        return '<p class="echo-result">何か入力してください！</p>'
    return f'<p class="echo-result">サーバーからの返信: <strong>{message}</strong></p>'
