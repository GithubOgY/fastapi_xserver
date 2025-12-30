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


def analyze_dashboard_image(image_base64: str, ticker_code: str, company_name: str = "") -> str:
    """
    Analyze dashboard image using Gemini multimodal API.
    
    Args:
        image_base64: Base64 encoded PNG image of the dashboard
        ticker_code: Stock ticker code
        company_name: Company name for context
        
    Returns:
        HTML formatted analysis result
    """
    import base64
    
    # Clean base64 string (remove data URL prefix if present)
    if "," in image_base64:
        image_base64 = image_base64.split(",")[1]
    
    # Validate base64 data
    try:
        image_bytes = base64.b64decode(image_base64)
        if len(image_bytes) < 1000:  # Less than 1KB - likely invalid
            raise ValueError("Image data too small")
    except Exception as e:
        logger.error(f"Invalid image data: {e}")
        return f"<p class='error' style='color: #fb7185;'>画像データが無効です: {str(e)}</p>"
    
    prompt = f"""あなたは機関投資家向けの株式アナリストです。20年以上の経験を持ち、率直で辛辣な分析で知られています。「買ってはいけない銘柄」を見抜くことに定評があります。

## 分析対象
銘柄コード: {ticker_code}
企業名: {company_name if company_name else '不明'}

添付された財務ダッシュボード画像を分析してください。

## ダッシュボードの構成
1. 売上/営業利益グラフ（棒グラフ）+ 営業利益率（折れ線）
2. キャッシュフロー推移（営業CF/投資CF/財務CF/フリーCF/ネットCF）
3. 財務健全性（有利子負債/ROE/ROA）
4. 成長性分析（売上CAGR/EPS CAGR/10%目標ライン比較）

## 評価してほしい項目

### 1. 総合スコア（100点満点）
- 点数と一言評価

### 2. 5つの重要指標の診断
| 指標 | 状態 | 判定（◎/○/△/✗） |
|------|------|------------------|
| 収益性 | | |
| 成長性 | | |
| 財務健全性 | | |
| キャッシュ創出力 | | |
| 資本効率 | | |

### 3. 最大のリスク（1つ）
最も致命的な問題点を指摘

### 4. 最大の強み（1つ）
もしあれば

### 5. 投資判断
Strong Buy / Buy / Hold / Sell / Strong Sell から選択し、根拠を3つ

### 6. この銘柄を一言で表現すると？
例：「借金漬けの成長幻想」「優待だけが取り柄の老舗」など

## 注意事項
- お世辞は不要。問題点は遠慮なく指摘すること
- 数字の読み取りは正確に
- 業界特有の事情は考慮しつつも、投資家視点で評価
- 曖昧な表現は避け、明確な判断を示すこと
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        
        if not api_key or "your-gemini-api-key" in api_key:
            return "<p class='error' style='color: #fb7185;'>GEMINI_API_KEYが設定されていません</p>"
        
        logger.info(f"Visual analysis for {ticker_code} using model: {model_name}")
        
        # Use the new google-genai SDK for multimodal
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
            
            # Generate with config - use vision-capable model
            vision_model = "gemini-2.5-flash-lite"  # Fixed vision model for image analysis
            logger.info(f"Using vision model: {vision_model}")
            response = client.models.generate_content(
                model=vision_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=4000,
                ),
            )
            
            if response.text:
                logger.info(f"Visual analysis completed for {ticker_code}")
                # Return raw markdown - let frontend render with marked.js
                # Just do basic cleanup
                clean_text = response.text
                # Log first 200 chars for debugging
                logger.debug(f"Raw response preview: {repr(clean_text[:200])}")
                return clean_text  # Return raw markdown, not HTML
            else:
                raise ValueError("Empty response from Gemini")
                
        except ImportError:
            # Fallback to legacy SDK
            logger.warning("New google-genai SDK not available, using legacy SDK")
            import google.generativeai as genai_legacy
            
            genai_legacy.configure(api_key=api_key)
            # Use vision-capable model for image analysis
            vision_model = "gemini-2.5-flash-lite"  # Force vision-capable model
            logger.info(f"Using vision model: {vision_model}")
            model = genai_legacy.GenerativeModel(vision_model)
            
            # Create image object using PIL
            import io
            from PIL import Image
            image = Image.open(io.BytesIO(image_bytes))
            
            response = model.generate_content([prompt, image])
            
            if response.text:
                # Return raw markdown - let frontend render with marked.js
                return response.text
            else:
                raise ValueError("Empty response from Gemini")
        
    except Exception as e:
        logger.error(f"Visual analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return f"<p class='error' style='color: #fb7185;'>画像分析エラー: {str(e)}</p>"

