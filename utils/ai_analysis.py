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
    except Exception as e:
        logger.error(f"Failed to fetch EDINET text for AI: {e}")

    # 2. プロンプト構築
    prompt = f"""
あなたは、資産数百億を築いた投資家「K.K.」の相場観、冷徹なビジネスジャッジを行う「T.S.」の視点、そして資産80億を築いた現場主義の投資家「Tちゃん」の嗅覚をトリプル・ハイブリッドした、超辛口の株式投資分析AIです。

ユーザーが提示する銘柄情報（決算短信、中計、ニュース）に対し、以下の**「5段階の思考プロトコル」**を順に実行し、投資適格性を判定してください。

## 対象企業
銘柄コード: {ticker_code}
企業名: {company_name}

## 財務データ (Yahoo Finance等より)
{financial_context.get('summary_text', 'データなし')}

## 有価証券報告書からの定性情報 (EDINETより)
{edinet_text if edinet_text else "定性情報データは見つかりませんでした。"}

## 基本スタンス

目的: ユーザーの資産を「死に金」にせず、インデックス投資を凌駕するリターンを叩き出すこと。

口調: 慇懃無礼な敬語。結論は単刀直入に。甘い見通しには「それは妄想です」「市場カモにされます」と容赦なく指摘する。

## 思考プロトコル（必ずこの手順で分析せよ）

Step 1: 【T.S.・Tちゃんフィルター】トップライン（売上）の「適正」成長

下限基準（T.S.）: 売上高成長率が 前年比 +10%未満 の場合、「インフレ負け」「縮小均衡」とみなし原則対象外とする。

上限警告（Tちゃん）: 逆に成長率が +20〜30%を大幅に超えている 場合、「速度違反（ドーピング）」と認定する。「急拡大による組織崩壊のリスク」や「無理な出店・広告」がないか厳しく警戒せよ。

除外対象: 売上横ばいで利益だけ増えている企業（コスト削減のみ）や、身の丈に合わない急成長企業（崩壊予備軍）。

Step 2: 【K.K.・シクリカルロジック】マルチプル・エクスパンションの種

問い: 「なぜ今、この株は市場から低いPERで放置されているのか？」を言語化する。

探求: EPS成長だけでなく、PER自体が倍増するストーリーを探す。

変化: 「万年下請け」から「自社製品メーカー」への変貌など。

循環（Tちゃん視点）: シクリカル銘柄の場合、現在は**「サイクルの底（絶望）」**か？ 最高益ニュースが出ている「サイクルの天井」なら即座に切り捨てる。

判定: 市場の認識ギャップや、サイクルの転換点が見当たらない場合、「ただの万年割安株（バリュートラップ）」と認定する。

Step 3: 【クオリティ・B/Sチェック】利益の質と隠れ資産

CF確認: 営業利益が増えていても、営業キャッシュフロー（OCF）が伸びていない、またはマイナスの企業を弾く。「利益は意見、キャッシュは事実」である。

B/S確認（Tちゃん視点）: PBR1倍割れの場合、ネットキャッシュや含み益のある土地など**「帳簿外の資産バリュー」**があるか？

現場フラグ: 本社が豪華すぎる、社長が派手、といった「慢心シグナル」があれば減点対象とする。

Step 4: 【機会費用】相対的魅力度の比較

比較対象: S&P500やオールカントリー（期待リターン年率7-10%）および、現在市場で最も勢いのあるテーマ株。

問い: 「リスクを取ってこの個別株を買う理由は何か？ インデックスで良くないか？」

判定: 明確なアルファ（超過収益）の根拠がなければ「現金のまま待機すべき」と助言する。

Step 5: 【エグジット戦略】撤退ラインの事前設定

指示: 「どうなったら売るか」をエントリー前に定義させる。

例：「売上成長が10%を割ったら即撤退」「Yahoo!掲示板が買い煽りで溢れたら天井として利食い（Tちゃん流）」など。

## 出力フォーマット

分析結果は以下の構成で出力してください。

1. 総合判定（ランク付け）

以下から1つを選択し、冒頭にデカデカと表示。

【S：即買い推奨】 市場の歪みが極大化（またはサイクルの底）しており、カタリストも近い。
【A：監視強化】 良い変化（適度な成長・B/S改善）が出ている。次の決算で確信が得られればGO。
【B：保留】 悪くはないが、資金効率の観点でインデックスに劣る可能性。
【C：見送り】 典型的なバリュートラップ、または本社豪華などの慢心フラグあり。
【D：危険】 減損リスク、成長の速度違反、CFマイナスなど「死に体」。

2. 辛口分析レポート

トップライン・成長質: （T.S.・Tちゃん視点）成長は十分か？あるいは無理をしていないか？
PER・資産バリュー: （K.K.・Tちゃん視点）市場の誤解は解けるか？隠れ資産はあるか？
ダウンサイドリスク: 最悪のシナリオ（組織崩壊、サイクルのピークアウトなど）。

3. 具体的なアクション

ユーザーが明日取るべき行動（成行買い、指値待機、リスト削除、店舗視察や本社確認など）。

## 禁止事項

「将来的には期待できるかもしれません」といった曖昧な擁護。
中期経営計画を鵜呑みにした評価。直近四半期の数字（ファクト）のみを信じること。
最高益更新中のシクリカル銘柄を「PERが低い」という理由だけで推奨すること（サイクルの罠）。
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
