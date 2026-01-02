import os
import logging
import google.generativeai as genai
import markdown
from typing import Dict, Any, Optional, TypedDict, List
from utils.edinet_enhanced import extract_financial_data, download_xbrl_package, get_document_list
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


# ========================================
# Phase 1: JSON構造定義
# ========================================

class AnalysisScores(TypedDict):
    """AI分析の5軸スコア"""
    profitability: int          # 収益性 (0-100)
    growth: int                 # 成長性 (0-100)
    financial_health: int       # 財務健全性 (0-100)
    cash_generation: int        # キャッシュ創出力 (0-100)
    capital_efficiency: int     # 資本効率 (0-100)


class StructuredAnalysisResult(TypedDict):
    """AI分析の構造化結果"""
    overall_score: int          # 総合スコア (0-100)
    investment_rating: str      # Strong Buy | Buy | Hold | Sell | Strong Sell
    scores: AnalysisScores      # 5軸スコア
    summary: str                # 総合評価コメント
    strengths: List[str]        # 強み（最大3つ）
    weaknesses: List[str]       # 弱み（最大3つ）
    recommendations: List[str]  # 投資判断の根拠（最大3つ）
    one_liner: str             # この銘柄を一言で表現

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
        "gemini-2.0-flash-lite-preview-02-05", # 2.0 Flash Lite
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
    import google.generativeai as genai_legacy

    for model_name in models_to_try:
        try:
            logger.info(f"Attempting AI analysis with model: {model_name}")
            
            # Use new Google GenAI SDK for 2.5/Lite models
            if "2.5" in model_name or "lite" in model_name:
                try:
                    from google import genai
                    from google.genai import types
                    
                    client = genai.Client(api_key=api_key)
                    
                    # Construct simple prompt content
                    contents = [
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=prompt)],
                        ),
                    ]
                    
                    # Generate with config
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            temperature=0.7,
                            max_output_tokens=4000,
                        ),
                    )
                    
                    if response.text:
                        return response.text
                    else:
                        logger.warning(f"New SDK returned empty text for {model_name}")
                        # Fallback to legacy loop or continue
                        
                except ImportError:
                    logger.warning("google-genai not installed, trying legacy SDK")
                except Exception as e_new:
                    logger.warning(f"New SDK failed for {model_name}: {e_new}")
                    # If this was a specific new model request, maybe legacy won't work either, 
                    # but we can let the loop continue to other models.
                    last_error = e_new
                    continue

            # Legacy SDK Fallback (or for standard models)
            genai_legacy.configure(api_key=api_key)
            model = genai_legacy.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                generation_config=genai_legacy.types.GenerationConfig(
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
            
    if last_error:
        raise last_error
    raise Exception("All models failed generation")

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
            priority_keys = ["経営者による分析", "財政状態の分析", "経営成績の分析", "キャッシュフローの状況", "事業等のリスク", "対処すべき課題", "設備投資の状況"]
            
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

**特記事項:**
提供された財務データ（数値）が不足している場合でも、直ちに「分析不可」と結論付けないでください。
「有価証券報告書からの定性情報」に含まれるテキストを精読し、そこから読み取れる企業の状況（増収増益の傾向、資金繰りの状況、投資の姿勢など）を最大限に活用して評価を行ってください。
特に銀行業や金融業の場合、一般的な指標（営業利益など）が適用できないことがあります。その場合は、業界特有の指標（経常利益、BIS基準自己資本比率など）や記述内容を重視してください。

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

## 重要: 言語指定
**すべての分析結果は必ず日本語で記述してください。**
- 総合判定の理由: 日本語で記述
- 成長性の評価: 日本語で記述
- バリュエーションの評価: 日本語で記述
- リスクと懸念点: 日本語で記述
- 財務健全性の評価: 日本語で記述
- アナリスト推奨アクション: 日本語で記述
- 英語での出力は厳禁です

分析結果はMarkdown形式で、すべて日本語で回答してください。

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


def analyze_financial_health(ticker_code: str, financial_context: Dict[str, Any], company_name: str = "") -> str:
    """
    💰 財務健全性分析
    キャッシュフローを中心に財務の安定性を評価
    """
    model = setup_gemini()
    if not model:
        return "<p class='error' style='color: #fb7185;'>Gemini APIキーが設定されていません</p>"
    
    # 財務データ + 経営者による分析のみ使用
    edinet_text = ""
    try:
        text_blocks = financial_context.get("edinet_data", {}).get("text_data", {})
        
        # 財務関連のテキストセクションを収集
        financial_keys = [
            "経営者による分析", 
            "財政状態の分析", 
            "経営成績の分析", 
            "キャッシュフローの状況",
            "経理の状況",
            "重要な会計方針"
        ]
        
        for key in financial_keys:
            if key in text_blocks and text_blocks[key]:
                # 各セクション2000文字程度に制限して連結
                content = text_blocks[key][:2000]
                edinet_text += f"\n### {key}\n{content}\n"
                
    except Exception as e:
        logger.error(f"Failed to extract EDINET data for financial analysis: {e}")
    
    prompt = f"""
あなたは財務分析の専門家です。
キャッシュフローを中心に、企業の財務健全性を厳格に評価してください。

## 対象企業
{company_name} ({ticker_code})

## 財務データ
{financial_context.get('summary_text', '財務データなし')}

## 経営陣の財務認識
{edinet_text if edinet_text else "経営者による分析データなし"}

## 分析項目
1. **営業CFの安定性** - 5年トレンドで評価
2. **フリーCFの健全性** - 投資余力の確認
3. **負債比率と自己資本比率** - 財務リスクの評価
4. **配当維持能力** - 株主還元の持続可能性
5. **総合的な財務リスク評価**

## 出力フォーマット
💰 **財務健全性: [S/A/B/C/D]**

### 📊 評価サマリー
- ✅ 強み: ...
- ⚠️ 懸念点: ...

### 📈 詳細分析

#### 1. キャッシュフロー分析
- 営業CF: ...
- フリーCF: ...

#### 2. 財務安全性
- 自己資本比率: ...
- 負債水準: ...

#### 3. 配当政策
- 配当性向: ...
- 配当継続性: ...

### 💡 投資家へのアドバイス
財務面から見た投資判断を明確に述べてください。

---

## 重要: 言語指定
**すべての分析結果は必ず日本語で記述してください。**
- 評価サマリー: 日本語で記述
- 詳細分析: 日本語で記述
- 投資家へのアドバイス: 日本語で記述
- 英語での出力は厳禁です

分析結果はMarkdown形式で、すべて日本語で回答してください。

---
**注意:** 本分析は参考情報であり、投資を保証するものではありません。
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        response_text = generate_with_fallback(prompt, api_key, model_name)
        return markdown.markdown(response_text, extensions=['extra', 'nl2br'])
    except Exception as e:
        logger.error(f"Financial analysis failed: {e}")
        return f"<p class='error' style='color: #fb7185;'>財務分析エラー: {str(e)}</p>"


def analyze_business_competitiveness(ticker_code: str, financial_context: Dict[str, Any], company_name: str = "") -> str:
    """
    🚀 事業競争力分析
    ビジネスモデルと成長戦略の実行力を評価
    """
    model = setup_gemini()
    if not model:
        return "<p class='error' style='color: #fb7185;'>Gemini APIキーが設定されていません</p>"
    
    # 事業関連データを抽出
    edinet_text = ""
    try:
        text_blocks = financial_context.get("edinet_data", {}).get("text_data", {})
        business_keys = ["事業の内容", "経営方針・経営戦略", "研究開発活動", "設備投資の状況"]
        
        for key in business_keys:
            if key in text_blocks:
                limit = 3000 if key in ["事業の内容", "経営方針・経営戦略"] else 2000
                edinet_text += f"### {key}\n{text_blocks[key][:limit]}\n\n"
        
        if not edinet_text:
            edinet_text = "事業・戦略情報が見つかりませんでした。"
    except Exception as e:
        logger.error(f"Failed to extract EDINET data for business analysis: {e}")
        edinet_text = "事業・戦略情報が見つかりませんでした。"
    
    prompt = f"""
あなたは事業戦略の専門家です。
企業のビジネスモデルと成長戦略の競争力を評価してください。

## 対象企業
{company_name} ({ticker_code})

## 事業・戦略情報
{edinet_text}

## 分析項目
1. **ビジネスモデルの競争優位性** - 収益構造・差別化要因
2. **参入障壁の高さ** - 技術力、ブランド、規制
3. **R&D投資の効果** - イノベーション力
4. **設備投資効率** - 成長投資の妥当性
5. **成長戦略の実現可能性** - 具体性と実績

## 出力フォーマット
🚀 **事業競争力: [S/A/B/C/D]**

### 📊 評価サマリー
- ✅ 競争優位性: ...
- 🎯 成長可能性: ...

### 📈 詳細分析

#### 1. ビジネスモデル評価
- 収益構造: ...
- 競争優位性: ...

#### 2. イノベーション力
- R&D投資水準: ...
- 技術力評価: ...

#### 3. 成長戦略
- 戦略の具体性: ...
- 実現可能性: ...

### 💡 投資家へのアドバイス
事業面から見た長期投資の可否を明確に述べてください。

---

## 重要: 言語指定
**すべての分析結果は必ず日本語で記述してください。**
- 評価サマリー: 日本語で記述
- 詳細分析: 日本語で記述
- 投資家へのアドバイス: 日本語で記述
- 英語での出力は厳禁です

分析結果はMarkdown形式で、すべて日本語で回答してください。

---
**注意:** 本分析は参考情報であり、投資を保証するものではありません。
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        response_text = generate_with_fallback(prompt, api_key, model_name)
        return markdown.markdown(response_text, extensions=['extra', 'nl2br'])
    except Exception as e:
        logger.error(f"Business analysis failed: {e}")
        return f"<p class='error' style='color: #fb7185;'>事業分析エラー: {str(e)}</p>"


def analyze_risk_governance(ticker_code: str, financial_context: Dict[str, Any], company_name: str = "") -> str:
    """
    ⚠️ リスク・ガバナンス分析
    投資リスクと経営の質を徹底評価
    """
    model = setup_gemini()
    if not model:
        return "<p class='error' style='color: #fb7185;'>Gemini APIキーが設定されていません</p>"
    
    # リスク・ガバナンスデータを抽出
    edinet_text = ""
    try:
        text_blocks = financial_context.get("edinet_data", {}).get("text_data", {})
        risk_keys = ["事業等のリスク", "対処すべき課題", "コーポレートガバナンス", "従業員の状況", "サステナビリティ"]
        char_limits = {
            "事業等のリスク": 4000,
            "対処すべき課題": 2000,
            "コーポレートガバナンス": 1500,
            "従業員の状況": 1500,
            "サステナビリティ": 1500,
        }
        
        for key in risk_keys:
            if key in text_blocks:
                limit = char_limits.get(key, 1500)
                edinet_text += f"### {key}\n{text_blocks[key][:limit]}\n\n"
        
        if not edinet_text:
            edinet_text = "リスク・ガバナンス情報が見つかりませんでした。"
    except Exception as e:
        logger.error(f"Failed to extract EDINET data for risk analysis: {e}")
        edinet_text = "リスク・ガバナンス情報が見つかりませんでした。"
    
    prompt = f"""
あなたはリスク管理とガバナンスの専門家です。
投資リスクと経営の質を徹底的に評価してください。

## 対象企業
{company_name} ({ticker_code})

## リスク・ガバナンス情報
{edinet_text}

## 分析項目（最重要）
1. **事業リスクの具体性と規模**
   - 為替リスク
   - サプライチェーンリスク
   - 競争リスク
   - 規制リスク
   - その他固有リスク
2. **リスク対応力** - 課題認識と対策の妥当性
3. **ガバナンス体制の透明性** - 取締役会構成、内部統制
4. **人材戦略・従業員満足度** - 組織力の評価
5. **ESGリスク** - 長期的持続可能性

## 出力フォーマット
⚠️ **リスク・ガバナンス: [S/A/B/C/D]**

### 📊 評価サマリー
- 🚨 主要リスク: ...
- ✅ ガバナンス評価: ...

### 📈 詳細分析

#### 1. 事業リスク分析（最重要）
- 為替・原材料リスク: ...
- 競争・規制リスク: ...
- リスク対応力: ...

#### 2. ガバナンス評価
- 経営体制: ...
- 透明性: ...

#### 3. ESG・人材
- 従業員状況: ...
- 持続可能性: ...

### 💡 投資家へのアドバイス
リスク面から見た投資判断を明確に述べてください。
リスクが重大な場合は、率直に「見送り」と評価してください。

---

## 重要: 言語指定
**すべての分析結果は必ず日本語で記述してください。**
- 評価サマリー: 日本語で記述
- 詳細分析: 日本語で記述
- 投資家へのアドバイス: 日本語で記述
- 英語での出力は厳禁です

分析結果はMarkdown形式で、すべて日本語で回答してください。

---
**注意:** 本分析は参考情報であり、投資を保証するものではありません。
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        response_text = generate_with_fallback(prompt, api_key, model_name)
        return markdown.markdown(response_text, extensions=['extra', 'nl2br'])
    except Exception as e:
        logger.error(f"Risk analysis failed: {e}")
        return f"<p class='error' style='color: #fb7185;'>リスク分析エラー: {str(e)}</p>"


def _validate_analysis_data(data: Dict) -> Dict:
    """
    Validate and sanitize AI analysis data to ensure correct ranges and types.

    Args:
        data: Raw analysis data from Gemini

    Returns:
        Validated and sanitized data
    """
    def clamp(value: int, min_val: int = 0, max_val: int = 100) -> int:
        """Clamp value to range"""
        try:
            val = int(value)
            return max(min_val, min(max_val, val))
        except (ValueError, TypeError):
            return 50  # Default to middle value

    # Validate overall_score
    data["overall_score"] = clamp(data.get("overall_score", 50))

    # Validate investment_rating
    valid_ratings = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    if data.get("investment_rating") not in valid_ratings:
        # Auto-assign rating based on overall_score
        score = data["overall_score"]
        if score >= 85:
            data["investment_rating"] = "Strong Buy"
        elif score >= 70:
            data["investment_rating"] = "Buy"
        elif score >= 50:
            data["investment_rating"] = "Hold"
        elif score >= 30:
            data["investment_rating"] = "Sell"
        else:
            data["investment_rating"] = "Strong Sell"

    # Validate scores object
    scores = data.get("scores", {})
    for key in ["profitability", "growth", "financial_health", "cash_generation", "capital_efficiency"]:
        scores[key] = clamp(scores.get(key, 50))
    data["scores"] = scores

    # Validate arrays (ensure they exist and limit length)
    for key in ["strengths", "weaknesses", "recommendations"]:
        arr = data.get(key, [])
        if not isinstance(arr, list):
            arr = []
        # Limit to 3 items and ensure strings
        data[key] = [str(item) for item in arr[:3]]

    # Validate strings
    data["summary"] = str(data.get("summary", "分析結果なし"))
    data["one_liner"] = str(data.get("one_liner", "評価不明"))

    return data


def analyze_dashboard_image(image_base64: str, ticker_code: str, company_name: str = "") -> Dict:
    """
    Analyze dashboard image using Gemini multimodal API (JSON structured output).

    Args:
        image_base64: Base64 encoded PNG image of the dashboard
        ticker_code: Stock ticker code
        company_name: Company name for context

    Returns:
        StructuredAnalysisResult dict with scores, ratings, and insights
    """
    import base64

    # Clean base64 string (remove data URL prefix if present)
    if "," in image_base64:
        image_base64 = image_base64.split(",")[1]

    # Validate base64 data
    try:
        image_bytes = base64.b64decode(image_base64)
        image_size_kb = len(image_bytes) / 1024
        if len(image_bytes) < 1000:  # Less than 1KB - likely invalid
            raise ValueError("Image data too small")
        
        # 画像品質のログ出力（デバッグ用）
        logger.info(f"Image size: {image_size_kb:.2f} KB")
        
        # 画像の解像度を確認（PILを使用）
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            width, height = img.size
            logger.info(f"Image dimensions: {width}x{height} pixels")
            
            # 解像度が低すぎる場合は警告
            if width < 800 or height < 600:
                logger.warning(f"Image resolution may be too low for accurate analysis: {width}x{height}")
        except Exception as img_check_error:
            logger.warning(f"Could not check image dimensions: {img_check_error}")
            
    except Exception as e:
        logger.error(f"Invalid image data: {e}")
        raise ValueError(f"画像データが無効です: {str(e)}")

    # JSON Schema for structured output (relaxed constraints for better compatibility)
    json_schema = {
        "type": "object",
        "properties": {
            "overall_score": {"type": "integer"},
            "investment_rating": {"type": "string"},
            "scores": {
                "type": "object",
                "properties": {
                    "profitability": {"type": "integer"},
                    "growth": {"type": "integer"},
                    "financial_health": {"type": "integer"},
                    "cash_generation": {"type": "integer"},
                    "capital_efficiency": {"type": "integer"}
                }
            },
            "summary": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "weaknesses": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "one_liner": {"type": "string"}
        },
        "required": ["overall_score", "investment_rating", "scores", "summary", "strengths", "weaknesses", "recommendations", "one_liner"]
    }

    prompt = f"""あなたは機関投資家向けの株式アナリストです。20年以上の経験を持ち、率直で辛辣な分析で知られています。「買ってはいけない銘柄」を見抜くことに定評があります。

## 分析対象
銘柄コード: {ticker_code}
企業名: {company_name if company_name else '不明'}

添付された財務ダッシュボード画像を分析し、JSON形式で構造化された評価を返してください。

## 重要: 数値読み取りの精度向上
画像から数値を読み取る際は、以下の手順を厳密に守ってください：

1. **グラフの軸ラベルを確認**: Y軸の単位（億円、%など）を正確に読み取る
2. **数値の正確な読み取り**: グラフ上の数値やラベルを拡大して確認し、小数点以下も含めて正確に読み取る
3. **トレンドの確認**: 複数年のデータがある場合、各年の値を個別に読み取り、トレンドを正確に把握する
4. **単位の統一**: 億円、万円、%などの単位を混同しない
5. **計算の検証**: CAGR、利益率などの計算値は、読み取った生データから再計算して検証する

## ダッシュボードの構成
1. 売上/営業利益グラフ（棒グラフ）+ 営業利益率（折れ線）
   - 各年の売上高と営業利益を正確に読み取り、営業利益率を計算
   - グラフのY軸の単位（億円など）を確認
2. キャッシュフロー推移（営業CF/投資CF/財務CF/フリーCF/ネットCF）
   - 各CFの値を年ごとに正確に読み取り、プラス/マイナスを正確に判定
3. **有利子負債推移（独立したグラフ）**
   - **重要**: 有利子負債は専用の棒グラフで表示されている
   - Y軸の単位は「億円」であることを確認
   - 各年の有利子負債の値を正確に読み取り、**年次比較で増減を判定すること**
   - 減少傾向であれば「減少」、増加傾向であれば「増加」と判定
   - グラフの棒の高さを年ごとに比較し、トレンドを正確に把握すること
4. 財務効率性（ROE/ROA）
   - ROEとROAの数値を正確に読み取り（単位：%）
   - 折れ線グラフで表示されている
5. 成長性分析（売上CAGR/EPS CAGR/10%目標ライン比較）
   - CAGRの計算値とグラフ上の表示値を両方確認
   - 10%目標ラインとの比較を正確に行う

## 分析プロトコル（段階的評価）

### 第1段階: CFチェック（最重要の足切り）
**営業利益が伸びていても、営業CFがマイナスまたは横ばいの企業は除外せよ。**
- 営業利益と営業CFの乖離を必ず確認すること
- 営業利益が増加しているのに営業CFがマイナスまたは横ばいの場合、会計操作や在庫増加などの問題を示唆
- この条件に該当する企業は、他の指標が良好でも評価を大幅に下げること（最低でもC判定以下）

### 第2段階: 基本的な財務分析
- 売上/営業利益グラフから成長性と収益性を評価
- 財務健全性指標（自己資本比率、有利子負債、ROE、ROA）を確認
- 成長性分析（売上CAGR/EPS CAGR）を評価

### 第3段階: シクリカル判定
**過去最高益であっても、市況商品（半導体・素材・海運）の場合は『ピークアウト』を疑い、PEGレシオが低くても評価を下げること。**
- 業種が半導体、素材（化学・鉄鋼・非鉄金属など）、海運などの市況商品の場合
- 過去最高益や好調な業績であっても、景気循環のピークアウトの可能性を考慮
- PEGレシオが低く見えても、業績の反転リスクを織り込んで評価を下げること
- この判定はweaknessesに必ず記載すること

### 第4段階: 現場フラグ（経営の慢心チェック）
**IR資料が豪華すぎる、新社屋建設などの『慢心』が見られる場合は減点せよ。**
- 画像内にIR資料の過剰な装飾や豪華な表現が見られる場合
- 新社屋建設、本社移転などの大型投資が好業績時に実施されている場合
- これらの兆候は経営の慢心を示し、将来の業績悪化の前兆となる可能性がある
- 該当する場合は評価を1段階下げること（例：A→B、B→C）

### 最終判断: インデックス比較（足切りライン）
**S&P500（年率7-10%）のリスク調整後リターンを上回る明確な根拠がない場合はD判定とせよ。**
- この銘柄がS&P500の期待リターン（年率7-10%）を上回る明確な根拠がない場合
- リスクを考慮してもインデックス投資の方が合理的と判断される場合
- この条件に該当する企業は、他の指標が良好でもD判定（見送り）とすること
- 明確な超過収益の根拠がない限り、インデックス投資を推奨すること

## スコアリング基準（0-100点）

### overall_score（総合スコア）
- 90-100: 優良企業。成長性・収益性・財務健全性すべてに優れる
- 75-89: 良好。一部に懸念あるが投資価値あり
- 50-74: 平凡。インデックス投資の方が無難
- 25-49: 問題あり。投資は慎重に
- 0-24: 危険。投資不適格

### 5軸スコア（scores）
各指標を0-100点で評価：

**profitability（収益性）**
- 営業利益率15%以上: 80-100点
- 営業利益率10-15%: 60-79点
- 営業利益率5-10%: 40-59点
- 営業利益率5%未満: 0-39点

**growth（成長性）**
- 売上CAGR 10%以上: 80-100点
- 売上CAGR 5-10%: 60-79点
- 売上CAGR 0-5%: 40-59点
- マイナス成長: 0-39点

**financial_health（財務健全性）**
- 自己資本比率50%以上 & 有利子負債ゼロ: 90-100点
- 自己資本比率40%以上: 70-89点
- 自己資本比率20-40%: 50-69点
- 自己資本比率20%未満: 0-49点

**cash_generation（キャッシュ創出力）**
- 営業CF安定プラス & フリーCF潤沢: 80-100点
- 営業CFプラス & フリーCFプラス: 60-79点
- 営業CFプラス & フリーCFマイナス: 40-59点
- 営業CFマイナス: 0-39点

**capital_efficiency（資本効率）**
- ROE 15%以上: 80-100点
- ROE 10-15%: 60-79点
- ROE 5-10%: 40-59点
- ROE 5%未満: 0-39点

## 投資判定基準（investment_rating）
- **Strong Buy**: 総合85点以上。成長性・収益性・財務健全性すべてに優れ、リスクも限定的。かつ、S&P500を上回る明確な根拠がある
- **Buy**: 総合70-84点。良好だが一部に懸念。タイミング次第で検討可。S&P500を上回る可能性がある
- **Hold**: 総合50-69点。悪くはないが積極推奨はできない。インデックス投資の方が無難
- **Sell**: 総合30-49点。リスクが目立つ、成長性に疑問。投資は推奨しない
- **Strong Sell**: 総合29点以下。財務・成長性・リスクに重大な問題あり。投資不適格

**重要**: 上記の段階的評価プロトコル（第1段階〜最終判断）を必ず適用し、該当する条件があれば評価を下げること。

## 注意事項
- **段階的評価プロトコルの厳格な適用**: 第1段階（CFチェック）から最終判断（インデックス比較）まで、すべての段階を必ず確認し、該当する条件があれば評価を下げること
- **数値読み取りの最優先**: グラフから数値を読み取る際は、拡大して確認し、軸ラベル、単位、小数点以下まで正確に読み取ること
- **読み取った数値の記録**: 分析の根拠となる具体的な数値（例：売上高○○億円、営業利益率○○%）をsummaryに記載すること
- **足切り条件の優先適用**: 第1段階（CFチェック）や最終判断（インデックス比較）で該当する場合は、他の指標が良好でも評価を下げること
- お世辞は不要。問題点は遠慮なく指摘すること
- 業界特有の事情は考慮しつつも、投資家視点で厳格に評価
- 曖昧な表現は避け、明確な判断を示すこと
- strengthsとweaknessesは各最大3項目まで、簡潔に
- recommendationsは投資判断の具体的根拠を3つ
- one_linerはこの銘柄の本質を的確に表現する一言

## 重要: 言語指定
**すべてのテキスト出力は必ず日本語で記述してください。**
- summary: 日本語で記述
- strengths: すべての項目を日本語で記述
- weaknesses: すべての項目を日本語で記述
- recommendations: すべての項目を日本語で記述
- one_liner: 日本語で記述
- 英語での出力は厳禁です

JSON形式で回答してください（フィールド名は英語、値は日本語）。
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

        if not api_key or "your-gemini-api-key" in api_key:
            raise ValueError("GEMINI_API_KEYが設定されていません")

        logger.info(f"Visual analysis for {ticker_code} using model: {model_name}")

        # Use the new google-genai SDK for multimodal with JSON output
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            # Create image part from bytes
            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/png"
            )

            # Create text part
            text_part = types.Part.from_text(text=prompt)

            # Combine into content
            contents = [
                types.Content(
                    role="user",
                    parts=[image_part, text_part],
                ),
            ]

            # Generate with config - use vision-capable model with JSON response
            # より高精度なモデルを使用（画像分析の精度向上のため）
            vision_model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash-exp")  # より高精度なモデルに変更
            logger.info(f"Using vision model: {vision_model} with JSON output")
            response = client.models.generate_content(
                model=vision_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.2,  # 数値読み取りの精度向上のため温度を下げる（0.5→0.2）
                    max_output_tokens=2000,
                    response_mime_type="application/json",
                    response_schema=json_schema,
                ),
            )

            if response.text:
                logger.info(f"Visual analysis completed for {ticker_code}")
                # Parse JSON response
                try:
                    analysis_data = json.loads(response.text)

                    # Validate and sanitize scores
                    analysis_data = _validate_analysis_data(analysis_data)

                    logger.debug(f"Parsed JSON: overall_score={analysis_data.get('overall_score')}, rating={analysis_data.get('investment_rating')}")
                    return analysis_data
                except json.JSONDecodeError as je:
                    logger.error(f"Failed to parse JSON response: {je}")
                    logger.debug(f"Raw response: {response.text}")
                    raise ValueError(f"JSON解析エラー: {str(je)}")
            else:
                raise ValueError("Empty response from Gemini")

        except ImportError:
            # Fallback to legacy SDK (may not support JSON schema)
            logger.warning("New google-genai SDK not available, using legacy SDK with manual JSON parsing")
            import google.generativeai as genai_legacy

            genai_legacy.configure(api_key=api_key)
            # Use vision-capable model for image analysis - より高精度なモデルに変更
            vision_model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash-exp")  # より高精度なモデルに変更
            logger.info(f"Using vision model: {vision_model}")
            model = genai_legacy.GenerativeModel(vision_model)

            # Create image object using PIL
            import io
            from PIL import Image
            image = Image.open(io.BytesIO(image_bytes))

            # Add JSON format instruction to prompt
            json_prompt = prompt + "\n\nMUST return valid JSON matching this schema:\n" + json.dumps(json_schema, indent=2)
            response = model.generate_content(
                [json_prompt, image],
                generation_config=genai_legacy.types.GenerationConfig(
                    temperature=0.2,  # 数値読み取りの精度向上のため温度を下げる（0.5→0.2）
                    max_output_tokens=2000,
                )
            )

            if response.text:
                try:
                    # Clean response (remove markdown code blocks if present)
                    clean_text = response.text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.startswith("```"):
                        clean_text = clean_text[3:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()

                    analysis_data = json.loads(clean_text)

                    # Validate and sanitize scores
                    analysis_data = _validate_analysis_data(analysis_data)

                    logger.debug(f"Parsed JSON (legacy SDK): overall_score={analysis_data.get('overall_score')}")
                    return analysis_data
                except json.JSONDecodeError as je:
                    logger.error(f"Failed to parse JSON response (legacy SDK): {je}")
                    logger.debug(f"Raw response: {response.text}")
                    raise ValueError(f"JSON解析エラー: {str(je)}")
            else:
                raise ValueError("Empty response from Gemini")

    except Exception as e:
        logger.error(f"Visual analysis failed: {e}")
        import traceback
        traceback.print_exc()
        raise  # Re-raise to be handled by endpoint


# ========================================
# Phase 1.3: HTMLレンダリング関数
# ========================================

def _render_score_bar(score: int, label: str) -> str:
    """
    プログレスバーのHTML生成

    Args:
        score: スコア (0-100)
        label: ラベル（例: "収益性"）

    Returns:
        HTML string
    """
    # Color mapping
    if score >= 80:
        color = "#10b981"  # Green
        bg_color = "#d1fae5"
    elif score >= 60:
        color = "#3b82f6"  # Blue
        bg_color = "#dbeafe"
    elif score >= 40:
        color = "#f59e0b"  # Orange
        bg_color = "#fed7aa"
    else:
        color = "#ef4444"  # Red
        bg_color = "#fee2e2"

    return f"""
    <div style="margin-bottom: 1rem;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
            <span style="font-size: 0.875rem; font-weight: 500; color: #374151;">{label}</span>
            <span style="font-size: 0.875rem; font-weight: 700; color: {color};">{score}点</span>
        </div>
        <div style="width: 100%; background-color: {bg_color}; border-radius: 9999px; height: 0.5rem; overflow: hidden;">
            <div style="background-color: {color}; height: 100%; width: {score}%; transition: width 0.5s ease;"></div>
        </div>
    </div>
    """


def render_visual_analysis_html(analysis_data: Dict, is_from_cache: bool = False) -> str:
    """
    AI分析結果をHTML形式でレンダリング

    Args:
        analysis_data: StructuredAnalysisResult dict
        is_from_cache: キャッシュからの取得かどうか

    Returns:
        HTML string
    """
    overall_score = analysis_data.get("overall_score", 0)
    investment_rating = analysis_data.get("investment_rating", "Hold")
    scores = analysis_data.get("scores", {})
    summary = analysis_data.get("summary", "")
    strengths = analysis_data.get("strengths", [])
    weaknesses = analysis_data.get("weaknesses", [])
    recommendations = analysis_data.get("recommendations", [])
    one_liner = analysis_data.get("one_liner", "")

    # Rating color and badge
    rating_colors = {
        "Strong Buy": ("#10b981", "#d1fae5", "💎"),
        "Buy": ("#3b82f6", "#dbeafe", "👍"),
        "Hold": ("#f59e0b", "#fed7aa", "⏸️"),
        "Sell": ("#f97316", "#fed7aa", "⚠️"),
        "Strong Sell": ("#ef4444", "#fee2e2", "🚫")
    }
    rating_color, rating_bg, rating_emoji = rating_colors.get(investment_rating, ("#6b7280", "#f3f4f6", "❓"))

    # Cache badge
    cache_badge = ""
    if is_from_cache:
        cache_badge = """
        <div style="display: inline-block; background-color: #fef3c7; color: #92400e; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin-bottom: 1rem;">
            ⚡ キャッシュ (7日以内)
        </div>
        """
    else:
        cache_badge = """
        <div style="display: inline-block; background-color: #d1fae5; color: #065f46; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; margin-bottom: 1rem;">
            🆕 最新分析
        </div>
        """

    # Score board
    score_board = f"""
    <div style="background: linear-gradient(135deg, {rating_bg} 0%, #ffffff 100%); border: 2px solid {rating_color}; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; text-align: center;">
        <div style="font-size: 3rem; font-weight: 800; color: {rating_color}; margin-bottom: 0.5rem;">
            {overall_score}<span style="font-size: 1.5rem; color: #6b7280;">/100</span>
        </div>
        <div style="display: inline-block; background-color: {rating_color}; color: #ffffff; padding: 0.5rem 1.5rem; border-radius: 9999px; font-size: 1rem; font-weight: 700; margin-top: 0.5rem;">
            {rating_emoji} {investment_rating}
        </div>
        <div style="margin-top: 1rem; font-size: 1rem; color: #374151; font-style: italic;">
            "{one_liner}"
        </div>
    </div>
    """

    # Progress bars for 5 axes
    progress_bars = f"""
    <div style="background-color: #f9fafb; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem;">
        <h3 style="font-size: 1.125rem; font-weight: 700; color: #111827; margin-bottom: 1rem;">📊 5軸分析</h3>
        {_render_score_bar(scores.get('profitability', 0), '収益性')}
        {_render_score_bar(scores.get('growth', 0), '成長性')}
        {_render_score_bar(scores.get('financial_health', 0), '財務健全性')}
        {_render_score_bar(scores.get('cash_generation', 0), 'キャッシュ創出力')}
        {_render_score_bar(scores.get('capital_efficiency', 0), '資本効率')}
    </div>
    """

    # Summary
    summary_section = f"""
    <div style="background-color: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem;">
        <h3 style="font-size: 1rem; font-weight: 700; color: #1e40af; margin-bottom: 0.5rem;">💡 総合評価</h3>
        <p style="font-size: 0.875rem; color: #374151; line-height: 1.6; margin: 0;">{summary}</p>
    </div>
    """

    # Strengths and Weaknesses (2-column layout)
    strengths_html = "".join([f"<li style='margin-bottom: 0.5rem;'>{s}</li>" for s in strengths])
    weaknesses_html = "".join([f"<li style='margin-bottom: 0.5rem;'>{w}</li>" for w in weaknesses])

    strengths_weaknesses = f"""
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem;">
        <div style="background-color: #d1fae5; border-radius: 12px; padding: 1rem;">
            <h3 style="font-size: 1rem; font-weight: 700; color: #065f46; margin-bottom: 0.75rem;">✅ 強み</h3>
            <ul style="font-size: 0.875rem; color: #374151; line-height: 1.6; margin: 0; padding-left: 1.25rem;">
                {strengths_html if strengths_html else '<li>特筆すべき強みなし</li>'}
            </ul>
        </div>
        <div style="background-color: #fee2e2; border-radius: 12px; padding: 1rem;">
            <h3 style="font-size: 1rem; font-weight: 700; color: #991b1b; margin-bottom: 0.75rem;">⚠️ 弱み</h3>
            <ul style="font-size: 0.875rem; color: #374151; line-height: 1.6; margin: 0; padding-left: 1.25rem;">
                {weaknesses_html if weaknesses_html else '<li>特筆すべき弱みなし</li>'}
            </ul>
        </div>
    </div>
    """

    # Recommendations
    recommendations_html = "".join([f"<li style='margin-bottom: 0.5rem;'>{r}</li>" for r in recommendations])
    recommendations_section = f"""
    <div style="background-color: #fef3c7; border-radius: 12px; padding: 1rem; margin-bottom: 1rem;">
        <h3 style="font-size: 1rem; font-weight: 700; color: #92400e; margin-bottom: 0.75rem;">🎯 投資判断の根拠</h3>
        <ol style="font-size: 0.875rem; color: #374151; line-height: 1.6; margin: 0; padding-left: 1.25rem;">
            {recommendations_html if recommendations_html else '<li>根拠情報なし</li>'}
        </ol>
    </div>
    """

    # Combine all sections
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto;">
        {cache_badge}
        {score_board}
        {progress_bars}
        {summary_section}
        {strengths_weaknesses}
        {recommendations_section}
        <div style="text-align: center; font-size: 0.75rem; color: #9ca3af; margin-top: 2rem;">
            ⚠️ 本分析は参考情報であり、投資を保証するものではありません。投資判断は自己責任で行ってください。
        </div>
    </div>
    """

    return html



# ========================================
# Phase 2.3: 履歴保存・取得関数
# ========================================

def save_analysis_to_history(db, ticker_code: str, analysis_type: str, analysis_data: Dict) -> None:
    """
    AI分析結果を履歴テーブルに保存

    Args:
        db: SQLAlchemy Session
        ticker_code: 銘柄コード
        analysis_type: 分析タイプ（例: "visual"）
        analysis_data: StructuredAnalysisResult dict
    """
    from database import AIAnalysisHistory
    import json

    try:
        # Extract scores for database columns
        scores = analysis_data.get("scores", {})

        new_history = AIAnalysisHistory(
            ticker_code=ticker_code,
            analysis_type=analysis_type,
            analysis_json=json.dumps(analysis_data, ensure_ascii=False),
            overall_score=analysis_data.get("overall_score"),
            investment_rating=analysis_data.get("investment_rating"),
            score_profitability=scores.get("profitability"),
            score_growth=scores.get("growth"),
            score_financial_health=scores.get("financial_health"),
            score_cash_generation=scores.get("cash_generation"),
            score_capital_efficiency=scores.get("capital_efficiency"),
        )

        db.add(new_history)
        db.commit()
        logger.info(f"[History] Saved analysis for {ticker_code} (type={analysis_type})")

    except Exception as e:
        logger.error(f"[History] Failed to save analysis for {ticker_code}: {e}")
        db.rollback()


def get_analysis_history(db, ticker_code: str, analysis_type: str = "visual", limit: int = 10) -> List[Dict]:
    """
    AI分析履歴を取得（最新N件）

    Args:
        db: SQLAlchemy Session
        ticker_code: 銘柄コード
        analysis_type: 分析タイプ
        limit: 取得件数

    Returns:
        List of StructuredAnalysisResult dicts (新しい順)
    """
    from database import AIAnalysisHistory
    import json

    try:
        histories = db.query(AIAnalysisHistory).filter(
            AIAnalysisHistory.ticker_code == ticker_code,
            AIAnalysisHistory.analysis_type == analysis_type
        ).order_by(AIAnalysisHistory.created_at.desc()).limit(limit).all()

        result = []
        for h in histories:
            try:
                data = json.loads(h.analysis_json)
                # Add metadata
                data["_created_at"] = h.created_at.isoformat() if h.created_at else None
                data["_id"] = h.id
                result.append(data)
            except json.JSONDecodeError as je:
                logger.warning(f"[History] Failed to parse JSON for history ID {h.id}: {je}")
                continue

        logger.info(f"[History] Retrieved {len(result)} histories for {ticker_code}")
        return result

    except Exception as e:
        logger.error(f"[History] Failed to get history for {ticker_code}: {e}")
        return []


def cleanup_old_history(db, days: int = 90) -> int:
    """
    古い履歴を削除（90日以上前）

    Args:
        db: SQLAlchemy Session
        days: 保持日数（デフォルト: 90日）

    Returns:
        削除件数
    """
    from database import AIAnalysisHistory
    from datetime import datetime, timedelta, timezone

    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        deleted_count = db.query(AIAnalysisHistory).filter(
            AIAnalysisHistory.created_at < cutoff_date
        ).delete()

        db.commit()
        logger.info(f"[History Cleanup] Deleted {deleted_count} old records (older than {days} days)")
        return deleted_count

    except Exception as e:
        logger.error(f"[History Cleanup] Failed: {e}")
        db.rollback()
        return 0


# ============================================================
# Phase 3: トレンド分析・比較表示
# ============================================================

def analyze_trend(history: List[Dict]) -> Dict:
    """
    履歴データから前回との比較分析を行う

    Args:
        history: get_analysis_history()から取得した履歴リスト
                 (最新が先頭、古い順に並ぶ)

    Returns:
        トレンド分析結果:
        {
            "has_trend": bool,              # 比較データがあるか
            "analysis_count": int,          # 分析回数
            "score_change": int,            # 総合スコアの変化
            "trend": str,                   # "improving" | "worsening" | "stable"
            "rating_change": {              # 投資判定の変化
                "previous": str,
                "current": str,
                "changed": bool
            },
            "score_changes": {              # 各指標の変化
                "profitability": {"previous": int, "current": int, "change": int},
                "growth": {"previous": int, "current": int, "change": int},
                "financial_health": {"previous": int, "current": int, "change": int},
                "cash_generation": {"previous": int, "current": int, "change": int},
                "capital_efficiency": {"previous": int, "current": int, "change": int}
            }
        }
    """
    try:
        # 履歴が2件未満の場合、比較できない
        if len(history) < 2:
            return {
                "has_trend": False,
                "analysis_count": len(history)
            }

        # 最新と1つ前のデータを取得
        current = history[0]
        previous = history[1]

        # 総合スコアの変化を計算
        current_score = current.get("overall_score", 0)
        previous_score = previous.get("overall_score", 0)
        score_change = current_score - previous_score

        # トレンド判定 (±5ポイント以内はstable)
        if score_change > 5:
            trend = "improving"
        elif score_change < -5:
            trend = "worsening"
        else:
            trend = "stable"

        # 投資判定の変化
        current_rating = current.get("investment_rating", "")
        previous_rating = previous.get("investment_rating", "")
        rating_changed = current_rating != previous_rating

        # 各指標の変化を計算
        score_changes = {}
        current_scores = current.get("scores", {})
        previous_scores = previous.get("scores", {})

        for key in ["profitability", "growth", "financial_health", "cash_generation", "capital_efficiency"]:
            current_val = current_scores.get(key, 0)
            previous_val = previous_scores.get(key, 0)
            change = current_val - previous_val

            score_changes[key] = {
                "previous": previous_val,
                "current": current_val,
                "change": change
            }

        return {
            "has_trend": True,
            "analysis_count": len(history),
            "score_change": score_change,
            "trend": trend,
            "rating_change": {
                "previous": previous_rating,
                "current": current_rating,
                "changed": rating_changed
            },
            "score_changes": score_changes
        }

    except Exception as e:
        logger.error(f"[Trend Analysis] Failed: {e}")
        return {
            "has_trend": False,
            "analysis_count": 0
        }


def render_trend_comparison_html(trend_data: Dict) -> str:
    """
    トレンド比較結果をHTMLで表示

    Args:
        trend_data: analyze_trend()の返り値

    Returns:
        トレンド比較のHTML文字列
    """
    if not trend_data.get("has_trend"):
        return ""

    score_change = trend_data["score_change"]
    trend = trend_data["trend"]
    analysis_count = trend_data["analysis_count"]
    rating_change = trend_data["rating_change"]
    score_changes = trend_data["score_changes"]

    # トレンドバッジのアイコンと色
    if trend == "improving":
        trend_icon = "📈"
        trend_color = "#10b981"  # green
        trend_text = "改善"
    elif trend == "worsening":
        trend_icon = "📉"
        trend_color = "#ef4444"  # red
        trend_text = "悪化"
    else:
        trend_icon = "➡️"
        trend_color = "#6b7280"  # gray
        trend_text = "横ばい"

    # スコア変化の表示
    if score_change > 0:
        score_change_text = f"+{score_change}"
        score_change_color = "#10b981"
    elif score_change < 0:
        score_change_text = f"{score_change}"
        score_change_color = "#ef4444"
    else:
        score_change_text = "±0"
        score_change_color = "#6b7280"

    # 投資判定の変更表示
    rating_change_html = ""
    if rating_change["changed"]:
        rating_change_html = f"""
        <div style="margin-top: 12px; padding: 12px; background: linear-gradient(135deg, #1e293b 0%, #334155 100%); border-radius: 8px; border-left: 4px solid #3b82f6;">
            <div style="font-size: 13px; color: #94a3b8; margin-bottom: 4px;">投資判定の変更</div>
            <div style="font-size: 15px; font-weight: 600;">
                <span style="color: #94a3b8;">{rating_change['previous']}</span>
                <span style="margin: 0 8px; color: #64748b;">→</span>
                <span style="color: #60a5fa;">{rating_change['current']}</span>
            </div>
        </div>
        """

    # 各指標の変化表示
    score_labels = {
        "profitability": "収益性",
        "growth": "成長性",
        "financial_health": "財務健全性",
        "cash_generation": "キャッシュ創出力",
        "capital_efficiency": "資本効率"
    }

    score_rows_html = ""
    for key, label in score_labels.items():
        data = score_changes.get(key, {})
        prev = data.get("previous", 0)
        curr = data.get("current", 0)
        change = data.get("change", 0)

        # 変化の矢印と色
        if change > 0:
            change_arrow = "↑"
            change_color = "#10b981"
            change_text = f"+{change}"
        elif change < 0:
            change_arrow = "↓"
            change_color = "#ef4444"
            change_text = f"{change}"
        else:
            change_arrow = "→"
            change_color = "#6b7280"
            change_text = "±0"

        score_rows_html += f"""
        <tr>
            <td style="padding: 8px 12px; color: #cbd5e1; font-size: 14px;">{label}</td>
            <td style="padding: 8px 12px; text-align: center; color: #94a3b8; font-size: 14px;">{prev}</td>
            <td style="padding: 8px 12px; text-align: center; color: #e2e8f0; font-weight: 600; font-size: 14px;">{curr}</td>
            <td style="padding: 8px 12px; text-align: center; color: {change_color}; font-weight: 600; font-size: 14px;">
                {change_arrow} {change_text}
            </td>
        </tr>
        """

    # HTMLテンプレート
    html = f"""
    <div style="margin-bottom: 24px; padding: 20px; background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border-radius: 12px; border: 1px solid #334155; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
        <!-- トレンドヘッダー -->
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <div style="font-size: 32px;">{trend_icon}</div>
                <div>
                    <div style="font-size: 18px; font-weight: 700; color: #f1f5f9; margin-bottom: 4px;">
                        前回比較: <span style="color: {trend_color};">{trend_text}</span>
                    </div>
                    <div style="font-size: 13px; color: #94a3b8;">
                        総合スコア: <span style="color: {score_change_color}; font-weight: 600; font-size: 14px;">{score_change_text}pt</span>
                        <span style="margin-left: 12px;">（{analysis_count}回目の分析）</span>
                    </div>
                </div>
            </div>
        </div>

        {rating_change_html}

        <!-- 各指標の比較表 -->
        <div style="margin-top: 16px;">
            <div style="font-size: 14px; font-weight: 600; color: #cbd5e1; margin-bottom: 8px;">各指標の変化</div>
            <table style="width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden;">
                <thead>
                    <tr style="background: #334155;">
                        <th style="padding: 10px 12px; text-align: left; color: #94a3b8; font-size: 13px; font-weight: 600;">指標</th>
                        <th style="padding: 10px 12px; text-align: center; color: #94a3b8; font-size: 13px; font-weight: 600;">前回</th>
                        <th style="padding: 10px 12px; text-align: center; color: #94a3b8; font-size: 13px; font-weight: 600;">今回</th>
                        <th style="padding: 10px 12px; text-align: center; color: #94a3b8; font-size: 13px; font-weight: 600;">変化</th>
                    </tr>
                </thead>
                <tbody>
                    {score_rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """

    return html

