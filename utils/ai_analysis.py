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

    # 1. EDINETから定性情報を取得
    edinet_text = ""
    try:
        edinet_data = financial_context.get("edinet_data", {})
        if edinet_data and "text_data" in edinet_data:
            text_blocks = edinet_data["text_data"]
            # Priority order for prompt (most important first)
            priority_keys = ["事業等のリスク", "対処すべき課題", "経営者による分析", "研究開発活動"]
            
            # Add priority keys first
            for key in priority_keys:
                if key in text_blocks:
                    content = text_blocks[key]
                    edinet_text += f"\n### {key}\n{content[:3000]}\n"  # Increased limit to 3000 chars
            
            # Add any remaining keys
            for title, content in text_blocks.items():
                if title not in priority_keys:
                    edinet_text += f"\n### {title}\n{content[:2000]}\n"
            
            logger.info(f"AI Prompt: Included {len(text_blocks)} EDINET text blocks: {list(text_blocks.keys())}")
        else:
            logger.warning(f"AI Prompt: edinet_data structure issue. edinet_data keys: {list(edinet_data.keys()) if edinet_data else 'None'}")
    except Exception as e:
        logger.error(f"Failed to fetch EDINET text for AI: {e}")

    # DEBUG: Log edinet_text length and preview
    logger.info(f"AI Prompt: edinet_text length = {len(edinet_text)} chars")
    if edinet_text:
        logger.info(f"AI Prompt: edinet_text preview (first 200 chars): {edinet_text[:200]}")
    else:
        logger.warning("AI Prompt: edinet_text is EMPTY - AI will receive fallback message!")

    # 2. プロンプト構築
    prompt = f"""
あなたは、プロフェッショナルな投資アナリストです。
厳格で客観的な視点から、データに基づいた率直な評価を提供してください。

**重要な原則:**
- 感情的な配慮は不要です。事実とデータのみに基づいて判断してください。
- リスクや懸念点は明確に指摘してください。遠慮は不要です。
- 投資に値しない銘柄には、はっきりと「見送り」「慎重に」と評価してください。
- 曖昧な表現を避け、具体的な数値と根拠を示してください。

## 対象企業
銘柄コード: {ticker_code}
企業名: {company_name}

## 財務データ (Yahoo Finance等より)
{financial_context.get('summary_text', 'データなし')}

## 有価証券報告書からの定性情報 (EDINETより)
{edinet_text if edinet_text else "定性情報データは見つかりませんでした。"}

## 分析プロトコル

**Step 1: 成長性の検証**
- 売上高成長率が年率10%を持続的に達成しているか？
- 成長の質は高いか？（一時的要因ではないか）
- 成長が鈍化している兆候はないか？
- **基準未達の場合、明確に指摘すること。**

**Step 2: バリュエーションの厳格評価**
- PER、PBRは業界平均と比較して妥当か？
- 高PERの場合、それを正当化する成長性があるか？
- 割高と判断される場合、投資タイミングとして不適切であることを明記すること。

**Step 3: 財務健全性とリスク分析（最重要）**
- 営業キャッシュフローは安定してプラスか？
- 自己資本比率は十分か？有利子負債の水準は？
- **EDINETの「事業等のリスク」セクションを必ず精査し、具体的なリスク要因（為替、原材料、規制、競合、技術革新リスクなど）を列挙すること。**
- リスクが重大な場合、投資判断を厳しく下げること。

**Step 4: 投資効率とROI**
- S&P500などのインデックスと比較して、リスクに見合うリターンが期待できるか？
- 明確な超過収益の根拠がない場合、「インデックス投資の方が無難」と率直に伝えること。

**Step 5: 総合判定**
- データが不十分な場合、「判断材料不足」と明記すること。
- 弱点やリスクを隠さず、すべて開示すること。

## 出力フォーマット

### 1. 総合判定（必ず1つ選択）
- **S（強く推奨）**: 成長性・割安性・財務健全性すべてに優れ、リスクも限定的。明確な投資根拠がある。
- **A（推奨）**: 良好だが一部に懸念あり。タイミングや価格次第で検討可。
- **B（様子見）**: 悪くはないが、積極的に推奨できる要素に欠ける。インデックスの方が無難。
- **C（慎重に）**: リスクが目立つ、または成長性に疑問。投資は推奨しない。
- **D（見送り）**: 財務・成長性・リスクのいずれかに重大な問題あり。投資不適格。

### 2. 詳細評価

#### 成長性
- 具体的な数値（売上成長率、利益成長率）を示し、評価すること。
- 成長鈍化の兆候があれば明記すること。

#### バリュエーション
- PER、PBRの水準を業界や過去と比較し、割高・割安を判定すること。
- 割高な場合、「投資タイミングとして不適切」と明記すること。

#### リスクと懸念点（必須セクション）
- **EDINETから抽出された「事業等のリスク」の内容を必ず要約し、具体的なリスク要因を箇条書きで列挙すること。**
- 以下のリスクカテゴリについて言及すること：
  - 為替リスク
  - 原材料価格変動リスク
  - 競争激化リスク
  - 規制・法的リスク
  - 技術革新リスク
  - その他、企業固有のリスク
- リスクが投資判断にどう影響するか、率直に評価すること。

#### 財務健全性
- キャッシュフロー、自己資本比率、負債水準を評価すること。
- 懸念がある場合、明確に指摘すること。

### 3. アナリスト推奨アクション
- 「買い」「様子見」「見送り」のいずれかを明示すること。
- 推奨理由を簡潔に述べること。
- 条件付き推奨の場合（例：「株価が〇〇円以下なら検討可」）、その条件を具体的に示すこと。

---

**最後に:** 投資判断は自己責任です。本分析は参考情報であり、投資を保証するものではありません。
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
