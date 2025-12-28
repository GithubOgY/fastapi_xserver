import os
import logging
import google.generativeai as genai
import markdown
from typing import Dict, Any, Optional
from utils.edinet_enhanced import extract_financial_data, download_xbrl_package, get_document_list
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def setup_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    
    # Check for missing or placeholder key
    if not api_key or "your-gemini-api-key" in api_key:
        logger.warning("GEMINI_API_KEY is not set or is a placeholder.")
        return None
    
    genai.configure(api_key=api_key)
    
    # Try to list models to confirm, or just return the model object
    # We will handle the 404 in the generation call by retrying with fallbacks
    return genai.GenerativeModel(model_name)

def generate_with_fallback(prompt: str, api_key: str, preferred_model: str) -> str:
    """Try to generate content with preferred model, fallback if not found"""
    models_to_try = [
        preferred_model, 
        "gemini-1.5-flash", 
        "gemini-1.5-flash-latest", 
        "gemini-2.0-flash", 
        "gemini-2.0-flash-exp",
        "gemini-flash-latest",
        "gemini-pro"
    ]
    # Remove duplicates while preserving order
    models_to_try = list(dict.fromkeys(models_to_try))
    
    last_error = None
    import google.generativeai as genai

    for model_name in models_to_try:
        try:
            logger.info(f"Attempting AI analysis with model: {model_name}")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    candidate_count=1,
                    max_output_tokens=4000,
                    temperature=0.7,
                )
            )
            return response.text
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            last_error = e
            if "API key not valid" in str(e):
                raise e # Don't retry invalid keys
            
            # If 404, let's try to list models for debugging once
            if "not found" in str(e).lower() and model_name == models_to_try[-1]:
                try:
                    available_models = [m.name for m in genai.list_models()]
                    logger.error(f"Available models for this key: {available_models}")
                except Exception as list_err:
                    logger.error(f"Failed to list models: {list_err}")
            continue
            
    raise last_error

def analyze_stock_with_ai(ticker_code: str, financial_context: Dict[str, Any], company_name: str = "") -> str:
    """
    Generate stock analysis using Gemini 1.5 Flash.
    Combines Yahoo Finance data with EDINET qualitative data if available.
    """
    model = setup_gemini()
    if not model:
        return """
        <div class="error-box" style="padding: 1rem; border: 1px solid #f43f5e; border-radius: 8px; background: rgba(244, 63, 94, 0.1); color: #f43f5e;">
            <p style="font-weight: bold; margin-bottom: 0.5rem;">⚠️ APIキー設定エラー</p>
            <p style="font-size: 0.9rem;">GeminiのAPIキーが正しく設定されていません。</p>
            <p style="font-size: 0.85rem; margin-top: 0.5rem;"><code>.env</code>ファイルの <code>GEMINI_API_KEY</code> に有効なキーを設定し、サーバーを再起動してください。</p>
        </div>
        """

    # 1. EDINETから定性情報を取得（試行）
    edinet_text = ""
    try:
        # 直近30日の書類を取得（有価証券報告書 or 四半期報告書）
        from main import get_latest_edinet_doc_id_by_ticker # 必要に応じてmainからインポート
        doc_id = None
        # main.py の既存ロジックを流用して doc_id を特定することを想定
        # ここでは後ほど main.py 側で doc_id を渡すか、内部で検索する
        # ※ 実装の簡略化のため、financial_context に edinet_data が入っているか確認する
        edinet_data = financial_context.get("edinet_data", {})
        if edinet_data and "text_data" in edinet_data:
            text_blocks = edinet_data["text_data"]
            for title, content in text_blocks.items():
                edinet_text += f"\n### {title}\n{content[:2000]}\n" # プロンプトサイズを考慮して制限
            logger.info(f"AI Prompt: Included {len(text_blocks)} EDINET text blocks for context.")
    except Exception as e:
        logger.error(f"Failed to fetch EDINET text for AI: {e}")

    # 2. プロンプト構築
    prompt = f"""
あなたは、豊富な経験を持つ親切で賢明な投資アドバイザーAIです。
投資判断に迷っているユーザーに対し、データの裏付けと共に、具体的で分かりやすい助言を提供してください。

ユーザーが提示する銘柄情報（決算短信、中計、ニュース）に対し、以下の**「5段階の分析プロセス」**を実行し、優しく背中を押す、あるいはリスクを丁寧に指摘するレポートを作成してください。

## 対象企業
銘柄コード: {ticker_code}
企業名: {company_name}

## 財務データ (Yahoo Finance等より)
{financial_context.get('summary_text', 'データなし')}

## 有価証券報告書からの定性情報 (EDINETより)
{edinet_text if edinet_text else "定性情報データは見つかりませんでした。"}

## 基本スタンス

目的: ユーザーの大切な資産を守りつつ、堅実なリターンを目指すお手伝いをすること。
口調: 丁寧語（「です・ます」調）。親身で落ち着いたトーン。
重視点: 「なぜそう言えるのか？」を具体的な数値（売上成長率、PER、利益率など）を示して説明すること。

## 分析プロセス（この視点で分析してください）

Step 1: 【成長性の確認】
- 売上高は順調に伸びていますか？（年率+10%以上が目安）
- 逆に急激すぎませんか？（+30%超は反動リスクに注意）
- 具体的な直近の成長率を示して評価してください。

Step 2: 【割安度の評価】
- 現在のPERは過去や同業他社と比べてどうですか？
- PBRが1倍を割れている場合、資産価値（現金や不動産）に注目すべき点はありますか？
- 「なぜ市場はこの価格をつけているのか」を推測してください。

Step 3: 【質と健全性】
- 利益だけでなく、営業キャッシュフローはプラスですか？
- 財務基盤（自己資本比率など）は安心できる水準ですか？
- **重要:** EDINETの「事業等のリスク」や「対処すべき課題」セクションの内容を必ず確認し、具体的な懸念点（為替、原材料価格、法規制など）があれば明記してください。

Step 4: 【投資効率】
- S&P500などのインデックス投資と比較して、あえてこの銘柄を選ぶ理由（超過収益の可能性）はありますか？
- 明確な強み（競争優位性）が見当たらない場合は、正直に伝えてください。

Step 5: 【判断の目安】
- もし購入する場合、どのようなシナリオで利益確定・損切りすべきか、具体的な目安（例：成長率鈍化、PER○倍到達など）を提案してください。

## 出力フォーマット

分析結果は以下の構成で、読みやすく出力してください。

1. **総合判定**
以下から1つ選び、冒頭に表示してください。
【S：自信を持って推奨】 割安かつ成長性が高く、データが強く支持します。
【A：前向きに検討】 良い兆候があります。次の決算などを確認しつつ検討を。
【B：様子見】 悪くはありませんが、今はインデックスの方が無難かもしれません。
【C：慎重に】 リスク要因が目立ちます。詳細な分析が必要です。
【D：見送り推奨】 財務や成長性に重大な懸念があります。

2. **詳細分析レポート**
- **成長性と業績**: 具体的な数値（〇%増、〇億円など）を引用して評価してください。
- **割安性と資産価値**: PER、PBR、隠れ資産などの観点から解説してください。
- **リスクと課題**: 定性情報から読み取れる懸念点を、優しく指摘してください。

3. **あなたへのアドバイス**
ユーザーが明日どのような行動を取るべきか、具体的なステップを提案してください。
（例：「まずは100株だけ打診買いしてみる」「決算発表まで待つ」「ウォッチリストに入れて株価〇円を待つ」など）

## 心構え
専門用語を使いすぎず、初心者にも伝わる平易な言葉で説明してください。
必ず **「根拠となる具体的な数字」** を文中に含めてください。
"""

    try:
        # Use fallback mechanism
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        
        response_text = generate_with_fallback(prompt, api_key, model_name)
        
        # MarkdownをHTMLに変換
        analysis_html = markdown.markdown(response_text, extensions=['extra', 'nl2br'])
        return analysis_html
    except Exception as e:
        logger.error(f"AI Analysis failed: {e}")
        error_msg = str(e)
        if "API key not valid" in error_msg:
            return """
            <div class="error-box" style="padding: 1rem; border: 1px solid #f43f5e; border-radius: 8px; background: rgba(244, 63, 94, 0.1); color: #f43f5e;">
                <p style="font-weight: bold;">⚠️ APIキーが無効です</p>
                <p style="font-size: 0.9rem;">Google AI Studioで取得した正しいキーが設定されているか確認してください。</p>
            </div>
            """
        return f"<p class='error' style='color: #fb7185;'>分析の生成中にエラーが発生しました: {error_msg}</p>"
