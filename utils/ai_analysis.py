import os
import logging
import google.generativeai as genai
import markdown
from typing import Dict, Any, Optional, TypedDict, List
from utils.edinet_enhanced import extract_financial_data, download_xbrl_package, get_document_list
from datetime import datetime, timedelta
import json
import hashlib

logger = logging.getLogger(__name__)

# =========================================================
# Visual（画像診断）プロンプトのバージョン
# - DBキャッシュ無効化や「どのプロンプトで生成したか」の追跡に使う
# - プロンプト/禁止事項/出力仕様を変えたら必ず更新する
# =========================================================
VISUAL_ANALYSIS_PROMPT_VERSION = "2026-01-02-visual-v3"


def compute_image_hash(image_base64: str) -> str:
    """
    画像診断のキャッシュ判定用ハッシュ（先頭12桁）を返す。
    dataURLプレフィックスがあってもOK。
    """
    try:
        if not image_base64:
            return ""
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]
        digest = hashlib.sha256(image_base64.encode("utf-8")).hexdigest()
        return digest[:12]
    except Exception:
        return ""


def sanitize_visual_analysis_data(data: Dict) -> Dict:
    """キャッシュ経由でも同じサニタイズ（recommendationsフィルタ等）を適用するための公開ラッパー。"""
    return _validate_analysis_data(data)


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
    investment_rating: str      # S | A | B | C | D
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
あなたは厳しい投資家アクティビストです。
キャッシュフローを中心に、企業の財務健全性を厳格かつ辛辣に評価してください。

## 対象企業
{company_name} ({ticker_code})

## 財務データ
{financial_context.get('summary_text', '財務データなし')}

## 経営陣の財務認識
{edinet_text if edinet_text else "経営者による分析データなし"}

## 分析項目
1. **営業CFの内容** - 5年トレンドで評価
2. **フリーCFの内容** - 投資余力の確認
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

    # Validate investment_rating（S/A/B/C/D）
    valid_ratings = ["S", "A", "B", "C", "D"]
    if data.get("investment_rating") not in valid_ratings:
        # Auto-assign rating based on overall_score
        score = data["overall_score"]
        if score >= 85:
            data["investment_rating"] = "S"
        elif score >= 70:
            data["investment_rating"] = "A"
        elif score >= 50:
            data["investment_rating"] = "B"
        elif score >= 30:
            data["investment_rating"] = "C"
        else:
            data["investment_rating"] = "D"

    # Validate scores object
    scores = data.get("scores", {})
    for key in ["profitability", "growth", "financial_health", "cash_generation", "capital_efficiency"]:
        scores[key] = clamp(scores.get(key, 50))
    data["scores"] = scores

    # Validate arrays (ensure they exist and limit length)
    for key in ["strengths", "weaknesses"]:
        arr = data.get(key, [])
        if not isinstance(arr, list):
            arr = []
        # Limit to 3 items and ensure strings
        data[key] = [str(item) for item in arr[:3]]
    
    # 【重要】recommendations のフィルタリング（経営アドバイスを排除）
    recommendations = data.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    
    # 禁止ワードリスト（経営コンサルタント的な表現）
    forbidden_patterns = [
        "すべき", "べきである", "を検討", "検討する", "を目指す", "目指すべき",
        "改善を図る", "向上を図る", "強化を図る", "安定化を図る",
        "見直しを検討", "シフトを検討", "削減を検討", "向上策",
        "コスト構造", "収益性の改善", "ROEの改善", "ROE向上",
        "資本効率の改善", "財務リスク軽減", "M&Aを検討",
        "資産効率を向上", "キャッシュフローの安定化", "転換させる",
        "運転資金管理", "投資計画の見直し", "資本構成の見直し",
        "不要資産の売却"
    ]
    
    filtered_recommendations = []
    for rec in recommendations[:3]:
        rec_str = str(rec)
        # 禁止ワードが含まれているかチェック
        contains_forbidden = any(pattern in rec_str for pattern in forbidden_patterns)
        if contains_forbidden:
            # 禁止ワードが含まれている場合、投資家目線に強制変換
            logger.warning(f"経営アドバイスを検出・除外: {rec_str}")
            # スコアに基づいてデフォルトの投資家目線コメントに置換
            overall_score = data.get("overall_score", 50)
            if overall_score >= 70:
                filtered_recommendations.append("S&P500を上回る成長ストーリーが見える。監視継続")
            elif overall_score >= 50:
                filtered_recommendations.append("インデックスに劣後する可能性。Pass（見送り）")
            else:
                filtered_recommendations.append("経営陣に改善能力なし。現状がその証明。即時処分")
        else:
            filtered_recommendations.append(rec_str)
    
    # フィルタリング後のrecommendationsが空の場合、デフォルト値を設定
    if not filtered_recommendations:
        overall_score = data.get("overall_score", 50)
        if overall_score >= 70:
            filtered_recommendations = ["成長性・収益性に優れる。買い検討"]
        elif overall_score >= 50:
            filtered_recommendations = ["S&P500を上回る根拠が弱い。Pass（見送り）"]
        else:
            filtered_recommendations = ["構造的な問題あり。投資不適格"]
    
    data["recommendations"] = filtered_recommendations

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

    # キャッシュ無効化用：画像内容のハッシュ（先頭12桁）
    image_hash = compute_image_hash(image_base64)

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
            "overall_score": {"type": "integer", "description": "0-100の総合スコア"},
            "investment_rating": {"type": "string", "description": "S/A/B/C/Dのランク。S=即買い、A=監視強化、B=保留、C=見送り、D=危険"},
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
            "summary": {"type": "string", "description": "投資家視点での総合評価。トレンド分析とモメンタムを含む"},
            "strengths": {"type": "array", "items": {"type": "string"}, "description": "強み。具体的な数値とトレンドを含む"},
            "weaknesses": {"type": "array", "items": {"type": "string"}, "description": "弱み。致命的欠陥、成長不全など強い言葉で"},
            "recommendations": {
                "type": "array", 
                "items": {"type": "string"}, 
                "description": "【重要】投資判断の根拠。経営アドバイス禁止。「なぜ買わない/売る」の理由を書く。例：「ROIC 4%で放置＝経営陣に能力なし。即時処分」「成長率8%はインフレ負け。Pass」。禁止例：「コスト削減を検討」「M&Aを検討」「収益性改善」「〜すべき」「〜による改善」"
            },
            "one_liner": {"type": "string", "description": "銘柄の本質を表す一言。辛口でエッジの効いた表現"}
        },
        "required": ["overall_score", "investment_rating", "scores", "summary", "strengths", "weaknesses", "recommendations", "one_liner"]
    }

    prompt = f"""あなたは、資産数百億を築いた投資家「A」の相場観、冷徹なビジネスジャッジを行う「B」の視点、そして資産80億を築いた現場主義の投資家「C」の嗅覚をトリプル・ハイブリッドした、超辛口の株式投資分析AIです。

## 基本スタンス
**目的**: ユーザーの資産を「死に金」にせず、インデックス投資を凌駕するリターンを叩き出すこと。
**口調**: 慇懃無礼な敬語。結論は単刀直入に。甘い見通しには「それは妄想です」「市場でカモにされます」と容赦なく指摘する。
**哲学**: 「様子見」という言葉は辞書から消せ。「即買い」以外は全て「見送り」か「危険」である。

## 【最重要ルール】recommendations（投資判断の根拠）の書き方
**あなたは経営コンサルタントではない。投資家である。**
recommendationsには「会社がこうすべき」ではなく「なぜこの銘柄を買わない/売る/空売りするか」を書け。

### 絶対禁止（これを書いたら即失格）：
❌ 「コスト構造の見直しによる収益性改善」
❌ 「成長戦略の再構築による売上高成長率向上」
❌ 「資本効率の改善によるROE向上」
❌ 「新規事業またはM&Aを検討」
❌ 「有利子負債の削減」
❌ 「〜を検討」「〜すべき」「〜による改善」「〜を目指す」

### 正しい書き方（この形式で書け）：
✅ 「売上成長率+8%はインフレ負け。トップラインが伸びない企業に未来はない。Pass」
✅ 「ROIC 4%台で5年間放置。経営陣に資本コストの意識がない証拠。即時処分」
✅ 「営業CFマイナス。利益は粉飾の疑いあり。空売り検討」
✅ 「S&P500の年率7-10%を上回る根拠がない。インデックスで十分」

## 分析対象
銘柄コード: {ticker_code}
企業名: {company_name if company_name else '不明'}

添付された財務ダッシュボード画像を分析し、JSON形式で構造化された評価を返してください。

## 思考プロトコル（必ずこの5段階の手順で分析せよ）

### Step 1: 【B・Cフィルター】トップライン（売上）の「適正」成長
**下限基準（B視点）**: 売上高成長率が前年比+10%未満の場合、「インフレ負け」「縮小均衡」とみなし原則対象外とする。
**上限警告（C視点）**: 逆に成長率が+20〜30%を大幅に超えている場合、「速度違反（ドーピング）」と認定する。「急拡大による組織崩壊のリスク」や「無理な出店・広告」がないか厳しく警戒せよ。
**除外対象**: 
- 売上横ばいで利益だけ増えている企業（コスト削減のみ＝将来性なし）
- 身の丈に合わない急成長企業（崩壊予備軍）

### Step 2: 【A・シクリカルロジック】マルチプル・エクスパンションの種
**問い**: 「なぜ今、この株は市場から低いPERで放置されているのか？」を言語化する。
**探求**: EPS成長だけでなく、PER自体が倍増するストーリーを探す。
- 変化: 「万年下請け」から「自社製品メーカー」への変貌など。
- 循環（C視点）: シクリカル銘柄の場合、現在は「サイクルの底（絶望）」か？ 最高益ニュースが出ている「サイクルの天井」なら即座に切り捨てる。
**判定**: 市場の認識ギャップや、サイクルの転換点が見当たらない場合、「ただの万年割安株（バリュートラップ）」と認定する。

### Step 3: 【クオリティ・B/Sチェック】利益の質と隠れ資産
**CF確認**: 営業利益が増えていても、営業キャッシュフロー（OCF）が伸びていない、またはマイナスの企業を弾く。「利益は意見、キャッシュは事実」である。
**B/S確認（C視点）**: PBR1倍割れの場合、ネットキャッシュや含み益のある土地など「帳簿外の資産バリュー」があるか？
**現場フラグ**: 本社が豪華すぎる、社長が派手、といった「慢心シグナル」があれば減点対象とする。

### Step 4: 【機会費用】相対的魅力度の比較
**比較対象**: S&P500やオールカントリー（期待リターン年率7-10%）および、現在市場で最も勢いのあるテーマ株。
**問い**: 「リスクを取ってこの個別株を買う理由は何か？ インデックスで良くないか？」
**判定**: 明確なアルファ（超過収益）の根拠がなければ「現金のまま待機すべき」と助言する。

### Step 5: 【エグジット戦略】撤退ラインの事前設定
**指示**: 「どうなったら売るか」をエントリー前に定義させる。
**例**: 「売上成長が10%を割ったら即撤退」「掲示板が買い煽りで溢れたら天井として利食い」など。

## 重要: 数値読み取りの精度向上とモメンタム分析（最重要）
画像から数値を読み取る際は、以下の手順を厳密に守ってください：

1. **グラフの軸ラベルを確認**: Y軸の単位（億円、%など）を正確に読み取る
2. **数値の正確な読み取り**: グラフ上の数値やラベルを拡大して確認し、小数点以下も含めて正確に読み取る
3. **モメンタム分析の必須化（最重要）**: 
   - **CAGRという「過去を丸めた数字」に騙されるな。足元の「勢い（モメンタム）」を見よ**
   - 例：CAGRが8%でも、直近2年が減少・横ばいなら「ピークアウト＝失速」と判定すること
   - 例：売上高が2023年をピークに2024年、2025年が減少傾向なら、「増加傾向」ではなく「ピークアウト」と判定
   - **ビジネスにおいて重要なのは「過去の平均」ではなく「現在の勢い（モメンタム）」である**
   - 各年の値を個別に読み取り、**特に直近2-3年のトレンド（加速or失速）を重視**すること
   - ピークアウトの兆候があれば、CAGRがプラスでも「失速」「ピークアウト」と断定せよ
4. **トレンド分析（長期）**: 
   - 最初の年と最新の年を比較し、変化率を計算すること
   - 例：営業利益率が2021年に30%、2024年に15%の場合、「維持」ではなく「半減（50%減少）＝崩壊」と判定
5. **単位の統一**: 億円、万円、%などの単位を混同しない
6. **計算の検証**: CAGR、利益率などの計算値は、読み取った生データから再計算して検証する

**背景推測の重要性**: 数値を読み取った後、必ずその変化の背景や理由を推測すること。
- 売上が増加している場合：新規事業の拡大、既存事業の成長、M&A、価格上昇など
- 営業利益率が変化している場合：競争環境の変化、価格決定力の有無、規模の経済など
- 有利子負債が変化している場合：財務戦略の変更、資金調達方針の変化など
- キャッシュフローが悪化している場合：在庫増加、売掛金の増加、設備投資、運転資金の圧迫など
- これらの背景推測は、summaryやweaknesses/strengthsに含めること
- **ただし、recommendationsには背景推測ではなく「投資判断」を書くこと**

## ダッシュボードの構成（全6つのグラフセクション）
画像には以下のグラフが含まれています。すべてのグラフを確認し、漏れなく分析してください：

1. **売上/営業利益グラフ（棒グラフ）+ 営業利益率（折れ線）**
   - 各年の売上高と営業利益を正確に読み取り、営業利益率を計算
   - グラフのY軸の単位（億円など）を確認
   - **重要**: 営業利益率の推移を必ず確認すること。例：30%→15%は「維持」ではなく「半減」と判定
   - 最初の年と最新の年を比較し、変化率を計算すること（例：30%から15%への変化は-50%）

2. **キャッシュフロー推移（営業CF/投資CF/財務CF/フリーCF/ネットCF）**
   - 各CFの値を年ごとに正確に読み取り、プラス/マイナスを正確に判定
   - 営業CF、投資CF、財務CF、フリーCF、ネットCFのすべてを確認

3. **有利子負債推移（独立した専用グラフ）**
   - **重要**: 有利子負債は専用の棒グラフで表示されている（他のグラフとは別）
   - Y軸の単位は「億円」であることを確認
   - 各年の有利子負債の値を正確に読み取り、**年次比較で増減を判定すること**
   - 減少傾向であれば「減少」、増加傾向であれば「増加」と判定
   - グラフの棒の高さを年ごとに比較し、トレンドを正確に把握すること
   - このグラフは財務健全性評価において最重要指標の一つ

4. **財務効率性（ROE/ROA）**
   - ROEとROAの数値を正確に読み取り（単位：%）
   - 折れ線グラフで表示されている
   - 両指標の推移を確認し、改善傾向か悪化傾向かを判定

5. **成長性分析（売上CAGR/EPS CAGR/10%目標ライン比較）**
   - CAGRの計算値とグラフ上の表示値を両方確認
   - 10%目標ラインとの比較を正確に行う
   - 成長スコアカード（売上高CAGR、EPS CAGR、利益率トレンド）も確認

6. **高度な財務指標グラフ（重要：合格ライン付き）**
   画像内に「高度な財務指標」または「📊 高度な財務指標」というセクションがある場合、以下のグラフが含まれています。各グラフには合格ラインが表示されているので、それらを基準に評価してください：
   
   **6-1. ROE推移グラフ（折れ線グラフ）**
   - ROEの数値を正確に読み取り（単位：%）
   - **合格ラインの確認**: グラフ上に以下の基準線が表示されている
     - **8%ライン（最低合格ライン）**: 赤色の点線 - このラインを下回る場合は評価を下げること
     - **15%ライン（理想的水準）**: 緑色の点線 - このラインを上回る場合は高く評価すること
   - ROEが8%未満の場合は効率性に問題ありと判定
   - ROEが15%以上の場合は優良と判定
   
   **6-2. ROIC推移グラフ（折れ線グラフ）**
   - ROICの数値を正確に読み取り（単位：%）
   - **合格ラインの確認**: グラフ上に以下の基準線が表示されている
     - **8%ライン（最低合格ライン）**: 赤色の点線 - このラインを下回る場合は評価を下げること
     - **15%ライン（理想的水準）**: 緑色の点線 - このラインを上回る場合は高く評価すること
   - ROICが8%未満の場合は資本効率に問題ありと判定
   - ROICが15%以上の場合は優良と判定
   
   **6-3. 売上高YoY成長率グラフ（棒グラフ）**
   - 各年の売上高YoY成長率を正確に読み取り（単位：%）
   - **合格ラインの確認**: グラフ上に以下の基準線が表示されている
     - **10%ライン（最低合格ライン）**: 黄色の点線 - このラインを下回る場合は成長性に懸念ありと判定
     - **15%ライン（理想的水準）**: 緑色の点線 - このラインを上回る場合は高成長と判定
   - 売上高YoY成長率が10%未満の場合は成長性に問題ありと判定
   - 売上高YoY成長率が15%以上の場合は高成長と判定
   
   **6-4. EPS YoY成長率グラフ（棒グラフ）**
   - 各年のEPS YoY成長率を正確に読み取り（単位：%）
   - **合格ラインの確認**: グラフ上に以下の基準線が表示されている
     - **15%ライン（最低合格ライン）**: 黄色の点線 - このラインを下回る場合は成長性に懸念ありと判定
     - **20%ライン（理想的水準）**: 緑色の点線 - このラインを上回る場合は理想的な成長と判定
     - **50%ライン（要警戒ライン）**: 赤色の太めの破線 - このラインを上回る場合は「出来すぎ」の疑いありと判定（一過性の特需、資産売却益、反動減リスクを疑うこと）
   - EPS YoY成長率が15%未満の場合は成長性に問題ありと判定
   - EPS YoY成長率が20%以上の場合は理想的な成長と判定
   - EPS YoY成長率が50%超の場合は要警戒と判定し、weaknessesに必ず記載すること

**重要**: 画像内に上記6つのグラフセクションがすべて含まれていることを確認し、それぞれを漏れなく分析すること。特に高度な財務指標グラフ（セクション6）の合格ラインを基準に、各指標が合格ラインを満たしているかを厳格に評価すること。

## 詳細分析（5段階プロトコルの実行）

上記の5段階思考プロトコルに基づき、画像から読み取った数値を以下の観点で分析せよ：

### Step 1 詳細: トップライン成長の「適正」評価
- 売上高YoY成長率を各年ごとに読み取り、+10%未満なら「インフレ負け」「縮小均衡」と断定
- 逆に+30%超なら「速度違反（ドーピング）」と認定し、組織崩壊リスクを警告
- 売上横ばいで利益だけ増えている場合は「コスト削減頼み＝将来性なし」と断定
- **トレンド分析**: 直近2-3年のモメンタム（加速or失速）を重視。CAGRに騙されるな

### Step 2 詳細: マルチプル・エクスパンションの種
- PERやPBRが低い場合、「なぜ市場から放置されているのか？」を言語化
- EPS成長だけでなく、PER自体が倍増するストーリー（変化のカタリスト）を探す
- **シクリカル判定**: 半導体・素材・海運などの場合、最高益更新中は「サイクルの天井」として即切り捨て
- 市場の認識ギャップがなければ「バリュートラップ（万年割安株）」と断定

### Step 3 詳細: 利益の質とB/Sチェック
- **CF確認（最重要）**: 営業利益が増えても営業CFがマイナスor横ばいなら弾く。「利益は意見、キャッシュは事実」
- 営業利益と営業CFの乖離は「会計操作」「在庫積み増し」の証拠として断罪
- **B/S確認**: PBR1倍割れの場合、ネットキャッシュや含み益のある土地など「帳簿外の資産バリュー」を探す
- **現場フラグ**: 本社が豪華、IR資料が派手＝「慢心シグナル」として減点

### Step 4 詳細: 機会費用の比較
- S&P500（年率7-10%）を上回る明確な根拠がなければ「インデックスで良い」と断言
- 「リスクを取ってこの個別株を買う理由は何か？」を自問
- 明確なアルファ（超過収益）の根拠がなければ「現金のまま待機すべき」と助言

### Step 5 詳細: エグジット戦略の提示
- 「どうなったら売るか」を具体的に提示
- 例：「売上成長が10%を割ったら即撤退」「掲示板が買い煽りで溢れたら天井として利食い」

## スコアリング基準（0-100点）

### overall_score（総合スコア）
- 90-100: 優良企業。成長性・収益性・財務健全性すべてに優れる
- 75-89: 良好。一部に懸念あるが投資価値あり
- 50-74: 平凡。インデックス投資の方が無難
- 25-49: 問題あり。投資は慎重に
- 0-24: 危険。投資不適格

### 5軸スコア（scores）
各指標を0-100点で評価：

**profitability（収益性）** - 「セクター特性を考慮せよ」
- **重要**: 業種によって利益率の基準は異なる。IT企業とエネルギー・素材セクターを同じ基準で判断するな
- エネルギー・素材・小売など薄利多売セクター: **同業他社や過去の自社平均と比較**せよ
- 原油・原材料価格の影響を除いた「実力値」を推測せよ
- 営業利益率20%以上 & トレンド改善: 80-100点（優良）
- 営業利益率15-20%: 60-79点（まあまあ）
- 営業利益率10-15%: 40-59点（凡庸＝S&P500で十分）
- 営業利益率10%未満: セクター特性を考慮。構造的に低利益率セクターなら同業比較、そうでなければ0-39点（致命的欠陥）
- **トレンド悪化は問答無用で20点減点**（例：30%→15%は「崩壊」）
- **セクター特性を無視した評価は「素人の仕事」である**

**growth（成長性）** - 「CAGRに騙されるな。モメンタムを見よ」
- **最重要**: CAGRは「過去を丸めた数字」。足元の「勢い（モメンタム）」を見よ
- 例：CAGR 8%でも、直近2年が減少・横ばいなら「ピークアウト＝失速」と判定
- 売上CAGR 15%以上 & 直近もモメンタム維持: 80-100点（高成長）
- 売上CAGR 10-15% & モメンタム維持: 60-79点（まあまあ）
- 売上CAGR 5-10% or モメンタム失速: 30-59点（成長不全＝インフレ負け or ピークアウト）
- 売上CAGR 5%未満 or 直近減少傾向: 0-29点（市場から退場予備軍）
- **インフレ率（2-3%）とS&P500成長率（7-10%）を考慮せよ。8%成長は「実質マイナス成長」「敗北」である**
- **「増加傾向」と言う前に、直近2-3年のトレンドを必ず確認せよ。ピークアウトの兆候を見逃すな**

**financial_health（財務健全性）** - 「自己資本比率40%の罠に注意」
- **重要**: 自己資本比率が高くても、資本効率（ROIC）が低ければ「経営の怠慢（現金を寝かせている）」である
- B/Sがきれいでも、P/Lを作れない企業は株主にとって価値を破壊し続ける存在
- 自己資本比率だけで判断するな。「その資本を使ってどれだけ稼いでいるか（ROIC）」を問え
- 自己資本比率50%以上 & ROIC 10%以上: 80-100点（優良）
- 自己資本比率40%以上 & ROIC 8%以上: 60-79点（まあまあ）
- 自己資本比率40%以上 だが ROIC 8%未満: 30-49点（**経営の怠慢＝現金を寝かせている**）
- 自己資本比率40%未満 or 有利子負債増加傾向: 0-39点
- **「自己資本比率40%以上で安定」と言ったら「カモ確定」である**

**cash_generation（キャッシュ創出力）** - 「借金で配当を出していないか？」を確認せよ
- 営業CF安定プラス & フリーCF潤沢 & 借金なしで配当: 80-100点
- 営業CFプラス & フリーCFプラス: 60-79点
- 営業CFプラス & フリーCFマイナス（投資過多）: 40-59点
- 営業CFマイナス or 借金で配当: 0-39点（詐欺まがい）

**capital_efficiency（資本効率）** - 「ROIC 8%未満は資本コスト負け」
- **重要**: ROIC（投下資本利益率）が資本コスト（WACC、通常6-8%）を下回れば、株主価値を破壊している
- ROE 20%以上 & ROIC 15%以上 & トレンド改善: 80-100点（優良）
- ROE 15-20% & ROIC 10%以上: 60-79点（まあまあ）
- ROE 10-15% & ROIC 8%未満: 30-49点（**資本コスト負け＝株主価値を破壊**）
- ROE 10%未満 or ROIC 5%未満: 0-29点（致命的欠陥＝株主への背任。経営陣に資本コストの意識がない）
- **ROIC 4-5%台で放置は「経営陣にその能力も意思もない」ことの証明である**

## 投資判定基準（investment_rating）- A・B・C式ランク付け

**重要**: 個人投資家に「様子見」という選択肢はない。以下のランクから1つを選択し、冒頭にデカデカと表示せよ。

- **S（即買い推奨）**: 総合85点以上。市場の歪みが極大化（またはサイクルの底）しており、カタリストも近い。「明日ストップ高になっても驚かない」レベル。今すぐ買え。
- **A（監視強化）**: 総合70-84点。良い変化（適度な成長・B/S改善）が出ている。次の決算で確信が得られればGO。マルチプル・エクスパンションのストーリーが見える。
- **B（保留）**: 総合50-69点。悪くはないが、資金効率の観点でインデックスに劣る可能性。S&P500で十分。監視リストに残すかは慎重に。
- **C（見送り）**: 総合30-49点。典型的なバリュートラップ、または本社豪華などの慢心フラグあり。認知リソースの無駄。リストから削除せよ。
- **D（危険）**: 総合29点以下。減損リスク、成長の速度違反、CFマイナスなど「死に体」。空売り検討。

**重要**: 
- 上記の5段階思考プロトコル（Step 1〜Step 5）を必ず適用し、該当する条件があれば評価を下げること
- 「Hold」「様子見」「要注視」などの中途半端な判定は禁止
- S&P500を凌駕する根拠がない場合は、どんなに良く見えても「B」または「C」である
- 最高益更新中のシクリカル銘柄（海運・半導体など）を「PERが低い」という理由だけで「S」「A」にすることは禁止（サイクルの罠）

## 注意事項（勝負師の魂を入れろ）

### 禁止事項（これをやったら「節穴」「素人」「カモ」確定）

**絶対禁止（これをやったら市場でカモにされます）**:
- **「将来的には期待できるかもしれません」といった曖昧な擁護の禁止**: それは妄想です。断言せよ
- **中期経営計画を鵜呑みにした評価の禁止**: 直近四半期の数字（ファクト）のみを信じること。経営計画は「願望」にすぎない
- **最高益更新中のシクリカル銘柄を「PERが低い」という理由だけで推奨することの禁止**: サイクルの罠。天井で買わせるな

**言葉の使用禁止**:
- **「Hold」「様子見」「要注視」という言葉の使用禁止**: 「即買い」以外は全て「Pass（見送り）」または「C（見送り）」「D（危険）」である
- **「課題がある」「改善の余地がある」という甘い言葉の使用禁止**: 「致命的欠陥」「成長不全」「市場から退場予備軍」と断定せよ
- **「良好」「健全」という教科書的な言葉の使用禁止**: 「金が遊んでいる」「資本効率が悪い」「株主への背任」と断定せよ
- **「可能性がある」という逃げの言葉の使用禁止**: 断言せよ

**経営アドバイスの禁止（最重要）**:
- **定型文の使用禁止**: 「M&Aを検討」「新規事業の展開」「コスト削減を期待」など、どこの会社でも言える定型文は禁止。固有のネタを見よ
- 「〜すべき」「〜を検討すべき」「〜による改善」は経営コンサルタントの仕事。絶対に書くな
- 投資家は「経営陣にその能力・意思があるか」だけを問い、「ないから売る」と断言せよ
- 例（禁止）: 「コスト構造の見直しによる収益性改善」「有利子負債の削減による財務リスク軽減」
- 例（正解）: 「経営陣にコスト削減の意思も能力もない。ROIC低迷で放置が証拠。即時処分」

**分析の禁止事項**:
- **CAGRだけを見て「増加傾向」と言うことの禁止**: 直近2-3年のモメンタム（加速or失速）を必ず確認せよ。ピークアウトを見逃すな
- **セクター特性を無視した評価の禁止**: 薄利多売セクター（エネルギー・素材・小売）にIT企業の利益率基準を当てはめるな
- **自己資本比率だけで「安定」と言うことの禁止**: ROIC（資本効率）と組み合わせて評価せよ。資本効率が悪ければ「経営の怠慢」である

### 必須事項（これをやらなければ「分析放棄」「素人の仕事」）
- **段階的評価プロトコルの厳格な適用**: 第1段階（CFチェック）から最終判断（死に金判定）まで、すべての段階を必ず確認し、該当する条件があれば評価を下げること
- **モメンタム分析の徹底（最重要）**: 
  - CAGRは「過去を丸めた数字」。足元の「勢い（モメンタム）」を見よ
  - 直近2-3年のトレンド（加速or失速）を必ず確認。ピークアウトの兆候（直近の減少・横ばい）があれば、CAGRがプラスでも「失速」「ピークアウト」と判定
  - 例：CAGR 8%でも直近2年が減少傾向なら「増加傾向」ではなく「ピークアウト＝失速」
  - 例：2023年をピークに2024年、2025年が減少なら「増加傾向」ではなく「トップラインがピークアウト」
- **トレンド分析（長期）の徹底**: 
  - 最初の年と最新の年を比較し、変化率を計算すること
  - 例：営業利益率30%→15%は「維持」ではなく「半減＝崩壊」と判定
  - 例：売上高CAGR 8%は「成長」ではなく「インフレ負け＝実質マイナス成長＝敗北」と判定
  - 例：有利子負債が増加している場合、「増加傾向にある可能性がある」ではなく「増加している。金利上昇局面で自殺行為」と断言すること
- **セクター特性の考慮**: 業種によって利益率の基準は異なる。薄利多売セクター（エネルギー・素材・小売）は同業他社や過去の自社平均と比較せよ
- **カタリストの有無の確認**: 経営陣に改善する能力・意思があるか？カタリスト（PBR1倍割れ是正圧力、アクティビスト、経営者交代等）があるか？
- **数値読み取りの最優先**: グラフから数値を読み取る際は、拡大して確認し、軸ラベル、単位、小数点以下まで正確に読み取ること
- **読み取った数値とモメンタムの記録**: 分析の根拠となる具体的な数値とモメンタム（例：売上高は2023年をピークに失速。CAGR 8%に騙されるな）をsummaryに記載すること
- **「株価が倍になるストーリー」の検証**: 教科書指標を計算して満足するな。「その数字が株価を倍にするストーリーにどう繋がるか？」だけを考えろ
- **機会費用と「死に金」判定**: S&P500を凌駕する根拠がない場合は、「資金拘束されるだけの『死に金』になる。即時処分」と断言せよ
- **背景推測の必須化**: 数値の変化を読み取ったら、必ずその背景や理由を推測し、summaryやweaknesses/strengthsに記載すること
- **足切り条件の優先適用**: 第1段階（CFチェック）や最終判断（死に金判定）で該当する場合は、他の指標が良好でも評価を下げること

### 言葉の研ぎ方（強い言葉を使え）
- 「課題がある」→「致命的欠陥」
- 「成長に期待」→「成長不全」「市場から退場予備軍」「トップラインがピークアウト」
- 「良好」「健全」→「金が遊んでいる」「資本効率が悪い」「経営の怠慢」
- 「改善の余地がある」→「経営陣にその能力も意思もない。現状がその証明」
- 「コスト削減を期待」→「お祈り」「それは投資ではない」
- 「リスクがある」→「自殺行為」「詐欺まがい」
- 「様子見」「Hold」→「Pass（見送り）」「即時処分」「死に金になる」「S&P500で十分」
- 「増加傾向」（CAGRだけ見て）→「ピークアウト」「失速」（モメンタムを見て）
- 「自己資本比率40%で安定」→「ROIC低迷＝経営の怠慢。カモ確定の評価」

### 出力の注意
- strengthsとweaknessesは各最大3項目まで、簡潔に（ただし具体的な数値とトレンドを含めること）

## 【最重要】recommendationsの書き方（経営アドバイスは絶対禁止）

**あなたは経営コンサルタントではない。投資家である。**
recommendationsには「会社がこうすべき」ではなく「なぜこの銘柄を買わない/売る/空売りするか」を書け。

### 絶対に書いてはいけない例（これを書いたら即失格）：
❌ 「コスト構造の見直しによる収益性改善」
❌ 「成長戦略の再構築による売上高成長率向上」
❌ 「資本効率の改善によるROE向上」
❌ 「新規事業またはM&Aを検討」
❌ 「有利子負債の削減による財務リスク軽減」
❌ 「資産効率化または財務レバレッジの見直し」
❌ 「利益率改善による企業価値向上を目指す」
❌ 「〜を検討」「〜すべき」「〜による改善」

### 正しい書き方の例（投資家視点での断罪）：
✅ 「売上成長率+8%はインフレ負け。トップラインが伸びない企業に未来はない。Pass」
✅ 「ROIC 4%台で5年間放置。経営陣に資本コストの意識がない証拠。即時処分」
✅ 「営業利益は増えているが営業CFはマイナス。利益は粉飾の疑いあり。空売り検討」
✅ 「最高益更新中だがシクリカル銘柄。サイクルの天井で買うのは自殺行為。見送り」
✅ 「PBR0.8倍だがカタリストなし。万年割安のバリュートラップ。認知リソースの無駄」
✅ 「成長率+35%は速度違反。組織崩壊リスクが高い。様子見ではなく見送り」
✅ 「自己資本比率50%だがROE 5%。金が遊んでいる。経営の怠慢。Pass」
✅ 「S&P500の年率7-10%を上回る根拠がない。インデックスで十分。リストから削除」

### recommendationsの書き方ルール：
1. 主語は「会社」ではなく「投資家としての私」
2. 「〜すべき」「〜を検討」は禁止。「〜だから買わない/売る」と書く
3. 経営陣の怠慢・無能を糾弾する形で書く
4. 具体的な数値とその解釈を必ず含める
5. 最終的な投資判断（Pass/売却/空売り/買い）を明記する

- one_linerはこの銘柄の本質を的確に表現する一言（「勝負師の魂」を込めた、エッジの効いた表現にすること）

## 重要: 言語指定とsummaryの記述方法
**すべてのテキスト出力は必ず日本語で記述してください。**

**summaryの記述方法（勝負師の魂を込めろ）**:
- **モメンタム分析を必ず含めること**: CAGRだけでなく、直近2-3年のトレンド（加速or失速）を記述。例：「CAGRは8%だが、2023年をピークに直近は失速。トップラインがピークアウト」
- 必ずトレンド（変化率）を含めること。例：「営業利益率は2021年30%から2024年15%へ半減＝崩壊している」のように、最初の年と最新の年を比較した変化を記載すること
- 「維持している」「一定水準を保っている」「増加傾向」などの甘い表現は禁止。モメンタムを確認せよ
- 数値の変化を正確に読み取り、変化率を計算してから記述すること
- **セクター特性を考慮した評価**: 薄利多売セクターは同業比較を記述。IT企業の基準を当てはめていないか確認
- **カタリストの有無**: 経営陣に改善する能力・意思があるか？カタリストがあるか？を記述
- 背景推測も含めること。例：「営業利益率が半減＝崩壊（競争激化による価格下落が背景。この会社に価格決定力はない。経営陣にコスト削減の意思もない）」
- 「株価が倍になるストーリー」が見えるか否かを明確に記述すること
- S&P500を凌駕する根拠があるか否かを明確に記述すること
- **「死に金」判定**: 構造的な低収益体質から脱却できていない場合は「資金拘束されるだけの『死に金』になる」と記述

- strengths: すべての項目を日本語で記述（具体的な数値とトレンドを含めること。「良好」などの甘い言葉は禁止）
- weaknesses: すべての項目を日本語で記述（「致命的欠陥」「成長不全」「自殺行為」などの強い言葉を使うこと）
- recommendations: **「なぜ買わない/売る/空売りするか」の根拠**を日本語で記述。
- one_liner: 日本語で記述（この銘柄の本質を的確に表現する、エッジの効いた一言。甘い言葉は禁止）
- 英語での出力は厳禁です

## 【最終確認】recommendationsの出力形式（これに従わない場合は即失格）

### ❌ 絶対に出力してはいけない例（経営アドバイス）：
```json
"recommendations": [
  "コスト構造の見直しによる収益性改善",
  "成長戦略の再構築による売上高成長率向上",
  "資本効率の改善によるROE向上",
  "有利子負債の削減による財務リスク軽減",
  "M&Aを検討",
  "〜すべき",
  "〜を目指す"
]
```

### ✅ 必ずこの形式で出力すること（投資家視点での断罪）：
```json
"recommendations": [
  "売上成長率+8%はインフレ負け。S&P500に劣後。Pass",
  "ROIC 4%で5年間放置。経営陣に資本コストの意識がない。即時処分",
  "営業CFがマイナス。利益は粉飾の疑いあり。空売り検討"
]
```

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

                    # キャッシュ無効化・追跡用メタデータ（UIでは非表示）
                    analysis_data["_prompt_version"] = VISUAL_ANALYSIS_PROMPT_VERSION
                    analysis_data["_image_hash"] = image_hash

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

                    # キャッシュ無効化・追跡用メタデータ（UIでは非表示）
                    analysis_data["_prompt_version"] = VISUAL_ANALYSIS_PROMPT_VERSION
                    analysis_data["_image_hash"] = image_hash

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
        # 新ランク（S/A/B/C/D）
        "S": ("#10b981", "#d1fae5", "💎"),
        "A": ("#3b82f6", "#dbeafe", "🚀"),
        "B": ("#f59e0b", "#fef3c7", "👀"),
        "C": ("#f97316", "#ffedd5", "⚠️"),
        "D": ("#ef4444", "#fee2e2", "🚨"),
        # 旧ランク（互換）
        "Strong Buy": ("#10b981", "#d1fae5", "💎"),
        "Buy": ("#3b82f6", "#dbeafe", "👍"),
        "Hold": ("#f59e0b", "#fed7aa", "⏸️"),
        "Sell": ("#f97316", "#fed7aa", "⚠️"),
        "Strong Sell": ("#ef4444", "#fee2e2", "🚫"),
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

