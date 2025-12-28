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
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    
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
    models_to_try = [preferred_model, "gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash-001", "gemini-pro"]
    # Remove duplicates while preserving order
    models_to_try = list(dict.fromkeys(models_to_try))
    
    last_error = None
    import google.generativeai as genai

    for model_name in models_to_try:
        try:
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
    except Exception as e:
        logger.error(f"Failed to fetch EDINET text for AI: {e}")

    # 2. プロンプト構築
    prompt = f"""
あなたはプロの証券アナリストです。以下の提供されたデータに基づき、客観的かつ洞察に満ちた分析レポートを日本語で作成してください。

## 対象企業
銘柄コード: {ticker_code}
企業名: {company_name}

## 財務データ (Yahoo Finance等より)
{financial_context.get('summary_text', 'データなし')}

## 有価証券報告書からの定性情報 (EDINETより)
{edinet_text if edinet_text else "定性情報データは見つかりませんでした。"}

## 指示
以下の構成でMarkdown形式で出力してください：
1. **総評**: 現在の状態を簡潔に（強気、中立、弱気など）。
2. **業績分析**: 数値から見える成長性や収益性の評価。
3. **定性分析・リスク評価**: EDINET情報がある場合、将来の課題やリスクについて。
4. **今後の展望**: 投資判断に資する予測。
5. **結論**: (Strong Buy / Buy / Hold / Sell) とその理由。

丁寧な日本語（敬体）で、読みやすく整形してください。
"""

    try:
        # Use fallback mechanism
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        
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
