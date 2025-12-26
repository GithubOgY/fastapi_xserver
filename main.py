from fastapi import FastAPI, Request, Form, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from typing import Annotated
from sqlalchemy.orm import Session
from database import SessionLocal, CompanyFundamental

app = FastAPI()

templates = Jinja2Templates(directory="templates")

# DBセッションの取得
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 起動時にデータをシードする
@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    if db.query(CompanyFundamental).count() == 0:
        # 7203.T トヨタ自動車のデータ (億円)
        data = [
            CompanyFundamental(
                ticker="7203.T",
                year=2024,
                revenue=450953.25,
                operating_income=53529.34,
                net_income=49449.33,
                eps=365.94
            ),
            CompanyFundamental(
                ticker="7203.T",
                year=2025,
                revenue=480367.04,
                operating_income=47955.86,
                net_income=47650.86,
                eps=359.56
            )
        ]
        db.add_all(data)
        db.commit()
    db.close()

# 簡易的なインメモリデータストア
state = {"counter": 0}

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    fundamentals = db.query(CompanyFundamental).filter(CompanyFundamental.ticker == "7203.T").all()
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "counter": state["counter"],
            "fundamentals": fundamentals,
            "ticker_name": "7203.T トヨタ自動車"
        }
    )

@app.post("/increment", response_class=HTMLResponse)
async def increment(request: Request):
    state["counter"] += 1
    return f'<span id="counter-value" class="counter-animate">{state["counter"]}</span>'

@app.post("/echo", response_class=HTMLResponse)
async def echo(message: Annotated[str, Form()]):
    if not message:
        return '<p class="echo-result">何か入力してください！</p>'
    return f'<p class="echo-result">サーバーからの返信: <strong>{message}</strong></p>'
