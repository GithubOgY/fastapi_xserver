from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from typing import Annotated

app = FastAPI()

templates = Jinja2Templates(directory="templates")

# 簡易的なインメモリデータストア
state = {"counter": 0}

# GET と HEAD 両方を許可する
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "counter": state["counter"]}
    )

@app.post("/increment", response_class=HTMLResponse)
async def increment(request: Request):
    state["counter"] += 1
    # htmx用の部分テンプレート（カウンター部分のみ）
    return f'<span id="counter-value" class="counter-animate">{state["counter"]}</span>'

@app.post("/echo", response_class=HTMLResponse)
async def echo(message: Annotated[str, Form()]):
    if not message:
        return '<p class="echo-result">何か入力してください！</p>'
    return f'<p class="echo-result">サーバーからの返信: <strong>{message}</strong></p>'
