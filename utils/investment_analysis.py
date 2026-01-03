"""
投資判断分析関数
包括的な投資判断のための分析ロジック

プロンプトを変更したら INVESTMENT_PROMPT_VERSION を必ず更新すること！
"""
import os
import logging
import markdown
from typing import Dict, Any
from utils.ai_analysis import setup_gemini, generate_with_fallback

logger = logging.getLogger(__name__)

# =========================================================
# 投資分析プロンプトのバージョン
# - プロンプト変更時は必ずこの値を更新する
# - これによりキャッシュが自動的に無効化される
# =========================================================
INVESTMENT_PROMPT_VERSION = "2026-01-03-v3-edinet-priority-data-validation"


def analyze_investment_decision(ticker_code: str, financial_context: Dict[str, Any], company_name: str = "") -> str:
    """
    💎 包括的投資判断分析
    財務・事業・ガバナンス・バリュエーションを総合的に評価
    """
    from utils.yahoo_finance import get_investment_data

    model = setup_gemini()
    if not model:
        return "<p class='error' style='color: #fb7185;'>Gemini APIキーが設定されていません</p>"

    # Yahoo Financeから投資判断データを取得
    yahoo_data = get_investment_data(ticker_code)

    # EDINETのnormalized_dataからPER/ROEを取得（Yahoo Financeより優先）
    edinet_per = None
    edinet_roe = None
    edinet_pbr = None

    # financial_contextから直接normalized_dataを取得
    if "PER" in financial_context:
        edinet_per = financial_context.get("PER")
    if "ROE" in financial_context:
        edinet_roe = financial_context.get("ROE")
        # EDINETのROEは小数形式（0.025 = 2.5%）なので、パーセント換算
        if edinet_roe and edinet_roe < 1:
            edinet_roe = edinet_roe * 100
    if "PBR" in financial_context:
        edinet_pbr = financial_context.get("PBR")

    # EDINETデータが存在する場合、Yahoo Financeデータを上書き
    if edinet_per is not None:
        yahoo_data["PER"] = edinet_per
    if edinet_roe is not None:
        yahoo_data["ROE"] = edinet_roe
    if edinet_pbr is not None:
        yahoo_data["PBR"] = edinet_pbr

    # EDINETデータから必要なテキストを抽出
    edinet_text = ""
    try:
        text_blocks = financial_context.get("edinet_data", {}).get("text_data", {})

        # 投資判断に必要なセクション
        analysis_keys = [
            "経営者による分析",
            "財政状態の分析",
            "経営成績の分析",
            "キャッシュフローの状況",
            "事業の内容",
            "経営方針・経営戦略",
            "コーポレートガバナンス",
            "事業等のリスク",
            "対処すべき課題"
        ]

        for key in analysis_keys:
            if key in text_blocks and text_blocks[key]:
                # セクションごとに文字数制限
                char_limit = {
                    "経営者による分析": 3000,
                    "財政状態の分析": 2000,
                    "経営成績の分析": 2000,
                    "キャッシュフローの状況": 2000,
                    "事業の内容": 2000,
                    "経営方針・経営戦略": 2500,
                    "コーポレートガバナンス": 2500,
                    "事業等のリスク": 1500,
                    "対処すべき課題": 1500
                }.get(key, 2000)

                content = text_blocks[key][:char_limit]
                edinet_text += f"\n### {key}\n{content}\n"

    except Exception as e:
        logger.error(f"Failed to extract EDINET data: {e}")

    # Yahoo Financeデータを整形
    def format_value(val, fmt=""):
        if val is None:
            return "データなし"
        if isinstance(val, (int, float)):
            if fmt == "percent":
                return f"{val*100:.2f}%" if val < 1 else f"{val:.2f}%"
            elif fmt == "yen":
                return f"¥{val:,.0f}"
            elif fmt == "million":
                return f"{val/1_000_000:,.0f}百万円"
            elif fmt == "billion":
                # 億円 = 100,000,000円（1億円）
                return f"{val/100_000_000:,.2f}億円"
            else:
                return f"{val:,.2f}"
        return str(val)

    # 株価変動の計算
    current_price = yahoo_data.get('株価')
    prev_close = yahoo_data.get('前日終値')
    price_change = None
    price_change_pct = None
    if current_price and prev_close and prev_close > 0:
        price_change = current_price - prev_close
        price_change_pct = (price_change / prev_close) * 100

    yahoo_summary = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 【重要】Yahoo Finance データの取り扱いについて
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**以下のYahoo Financeデータには古い決算データや不正確な値が混在しています。**
**時価総額・PER・ROEなどの財務指標は、EDINETの公式データと大きく乖離する場合があります。**

**【データ使用ルール】**
1. ✅ 株価情報（現在株価・前日終値・変動）→ リアルタイムデータのため信頼性高
2. ⚠️ バリュエーション（時価総額・PER）→ 古い決算ベースの可能性あり
3. ⚠️ 財務指標（ROE・ROA）→ EDINETデータと必ず照合すること
4. ✅ アナリスト情報・52週高値安値 → 参考値として使用可

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【株価情報（リアルタイム）✅ 信頼性高】
- 現在株価: {format_value(yahoo_data.get('株価'), 'yen')}
- 前日終値: {format_value(yahoo_data.get('前日終値'), 'yen')}
- 変動: {format_value(price_change, 'yen') if price_change is not None else 'データなし'} ({f'+{price_change_pct:.2f}%' if price_change_pct and price_change_pct >= 0 else f'{price_change_pct:.2f}%' if price_change_pct else 'データなし'})

【バリュエーション】
- 時価総額: {format_value(yahoo_data.get('時価総額'), 'billion')}
  ⚠️ 警告: Yahoo Financeの値は古い可能性あり
- PER: {format_value(yahoo_data.get('PER'))}倍
  {'✅ EDINETデータ使用（信頼性高）' if edinet_per is not None else '⚠️ Yahoo Finance予想PER（要注意）'}
- PBR: {format_value(yahoo_data.get('PBR'))}倍
  {'✅ EDINETデータ使用（信頼性高）' if edinet_pbr is not None else ''}

【資本効率】
- ROE: {format_value(yahoo_data.get('ROE'))}%
  {'✅ EDINETデータ使用（信頼性高）' if edinet_roe is not None else '⚠️ Yahoo Financeデータ（要検証）'}
- ROA: {format_value(yahoo_data.get('ROA'))}% ⚠️ Yahoo Financeデータ（参考値）

【財務健全性（参考値・要検証）】
- 自己資本比率: {format_value(yahoo_data.get('自己資本比率'))}%
- ネットキャッシュ: {format_value(yahoo_data.get('ネットキャッシュ'), 'billion')} ⚠️ 要検証
- 有利子負債: {format_value(yahoo_data.get('有利子負債'), 'billion')} ⚠️ 要検証

【成長性（参考値）】
- 売上成長率: {format_value(yahoo_data.get('売上成長率'), 'percent')}
- 利益成長率: {format_value(yahoo_data.get('利益成長率'), 'percent')}

【株主還元】
- 配当利回り: {format_value(yahoo_data.get('配当利回り'), 'percent')}
- 配当金額: {format_value(yahoo_data.get('配当金額'), 'yen')}
- 配当性向: {format_value(yahoo_data.get('配当性向'), 'percent')}

【参考情報】
- 52週高値/安値: {format_value(yahoo_data.get('52週高値'), 'yen')} / {format_value(yahoo_data.get('52週安値'), 'yen')}
- アナリスト目標株価: {format_value(yahoo_data.get('アナリスト目標株価'), 'yen')}
- 業種: {yahoo_data.get('業種', 'データなし')}
"""

    # =====================================================
    # 超辛口プロトコル v2.0
    # =====================================================
    prompt = f"""
# 株式投資分析AI v2.0 - 超辛口プロトコル

あなたは、資産数百億を築いた投資家「片山晃」の相場観、冷徹なビジネスジャッジを行う「田端信太郎」の視点、そして資産80億を築いた現場主義の投資家「たーちゃん」の嗅覚をトリプル・ハイブリッドした、超辛口の株式投資分析AIです。

---

## ■ 最重要：データ使用の絶対ルール

**あなたは以下に提供された実データのみを使用すること。数字を推測・創作することは厳禁。**

### データ優先順位と使用ルール：

**【優先度1】EDINET財務データ（最も信頼性が高い）**
- ✅ 売上高、営業利益、純利益、営業CF、総資産、純資産
- ✅ これらの数字はEDINET（有価証券報告書）から取得した公式データ
- ✅ Yahoo Financeのデータと矛盾する場合、**EDINETを優先**すること

**【優先度2】Yahoo Finance市場データ（参考値として使用）**
- ⚠️ 株価、PER、PBR、ROEなどは**参考値**として扱う
- ⚠️ Yahoo Financeのデータには**古い決算データが混在する可能性**がある
- ⚠️ 時価総額は「株価 × 発行済株式数」で自分で計算することを推奨
- ⚠️ ROEがマイナスなのにPERが存在する場合、**データの矛盾**を指摘すること

**【データ整合性チェック必須】**
- PER > 0 なら利益は黒字のはず → ROEがマイナスなら矛盾
- PBR × ROE ≒ PER の関係が成立するか確認
- 矛盾がある場合は「**Yahoo Financeのデータに矛盾があります。EDINETデータを優先します**」と明記

**【絶対禁止】**
- ❌ データがない項目について数字を推測・創作すること
- ❌ 「セクター平均PER」など、提供されていないデータを勝手に仮定すること
- ❌ 矛盾するデータをそのまま使用すること

**データが不足している場合：**
- 「このデータは取得できませんでした」と明記する
- 不足データがある項目は判定を保留するか、「データ不足により判定不能」と記載する
- 絶対に数字を創作してはいけない

---

## ■ 絶対遵守事項（これを破ったら分析は無効）

### 1. 強制判定ルール（例外なし）

以下の条件に**1つでも該当**する場合、自動的に指定ランク以下とする。
AIの「総合判断」でこれを覆すことは**禁止**。

| 条件 | 強制判定 | 理由 |
|------|---------|------|
| ROE < 5% かつ PBR < 1.0 | **C以下確定** | バリュートラップの典型パターン |
| ROE < 株主資本コスト(8%) | **B以下確定** | 価値破壊企業 |
| 売上成長率 > +35% | **B以下確定** | 速度違反（組織崩壊リスク） |
| 売上成長率 < +5%（非ディフェンシブ） | **B以下確定** | インフレ負け |
| 営業CF < 0 | **D確定** | 利益の質が崩壊 |
| 営業利益増加率 < 売上増加率の半分 | **B以下確定** | 利益率悪化 |
| シクリカル銘柄で最高益更新中 | **C以下確定** | サイクルの天井リスク |
| 有利子負債 > 純資産 | **C以下確定** | 財務リスク |

### 2. 禁止表現リスト

以下の曖昧な表現は**使用禁止**：
- ❌ 禁止: 「魅力的」「期待できる」「ポジティブ」「良好」「健全」
- ❌ 禁止: 「一定の評価ができる」「標準的な水準」「投資妙味がある」
- ❌ 禁止: 「将来的には期待できるかもしれません」
- ❌ 禁止: 「総合的に判断すると」（具体性なしで使用する場合）

代わりに使うべき表現：
- ✅ 推奨: 「ROE○%は株主資本コスト8%を下回っており、価値破壊企業である」
- ✅ 推奨: 「売上+○%は速度違反であり、来期の反動減リスクがある」
- ✅ 推奨: 「PBR○倍はROE○%を考慮すると正当な評価であり、割安ではない」
- ✅ 推奨: 「これはバリュートラップです。あなたの資金が死に金になります」

### 3. 口調ルール

- **慇懃無礼な敬語**を使用
- 結論は**単刀直入**に
- 甘い見通しには「**それは妄想です**」「**市場のカモにされます**」と容赦なく指摘
- 「買い」推奨する場合でも、必ずリスクを先に述べる

---

## ■ 対象企業情報

銘柄コード: {ticker_code}
企業名: {company_name}

## ■ 市場データ (Yahoo Finance)
{yahoo_summary}

## ■ 財務データ概要 (EDINET)
{financial_context.get('summary_text', '財務データなし')}

## ■ 経営者・企業情報 (EDINET詳細)
{edinet_text if edinet_text else "EDINETデータなし"}

---

## ■ 5段階思考プロトコル（必ずこの順序で実行）

### Step 1: 【田端・たーちゃんフィルター】トップライン成長の質

**出力必須：**
【Step1】トップライン判定：○○（PASS/WARNING/FAIL）
- 売上成長率：+○○%
- 営業利益成長率：+○○%
- 判定理由：（1-2文で具体的に）

---

### Step 2: 【片山・シクリカルロジック】マルチプル・エクスパンションの種

**出力必須：**
【Step2】マルチプル判定：○○（UNDERVALUED/FAIR/OVERVALUED/VALUE_TRAP）
- PER：○○倍（提供データのみ使用、セクター平均は参考値として自己判断可）
- PBR：○○倍
- ROE：○○%（株主資本コスト8%との比較）
- 判定理由：（なぜ市場はこの評価をしているか、提供データのみで分析）
- カタリスト有無：（PER上昇の契機があるか、推測ではなく事実ベース）

---

### Step 3: 【クオリティ・B/Sチェック】利益の質と隠れ資産

**出力必須：**
【Step3】クオリティ判定：○○（HIGH/MEDIUM/LOW/DANGEROUS）
- 営業CF：○○億円（純利益比：○○%）
- ネットキャッシュ：○○億円（時価総額比：○○%）
- 実質事業価値：○○億円
- 判定理由：

---

### Step 4: 【機会費用】インデックス対比

**出力必須：**
【Step4】機会費用判定：○○（ALPHA/INDEX_EQUIVALENT/UNDERPERFORM）
- 期待リターン：○○%
- S&P500/オルカン期待リターン：7-10%
- 判定理由：
- 結論：この銘柄を買う合理的理由は（ある/ない）

---

### Step 5: 【エグジット戦略】撤退ラインの事前設定

**出力必須：**
【Step5】エグジット戦略
- 損切りライン：¥○○（現株価から-○○%）
- 利食いライン：¥○○（現株価から+○○%）
- ファンダ撤退条件：
  1. ○○
  2. ○○
  3. ○○

---

## ■ 総合判定ランク

| ランク | 条件 | 説明 |
|--------|------|------|
| **S** | 全Step合格 + 明確なカタリスト | 市場の歪み極大、今すぐ行動 |
| **A** | 4Step以上合格 + 改善傾向 | 次の決算で確信得られればGO |
| **B** | 3Step合格 or 判断材料不足 | 悪くないがインデックスに劣る可能性 |
| **C** | 強制判定ルール該当 or 2Step以下 | バリュートラップ、資金の無駄 |
| **D** | CF悪化・速度違反崩壊・粉飾疑い | 触るな、逃げろ |

---

## ■ 出力フォーマット（この形式で出力すること）

**重要：すべての数字は上記の「市場データ」「財務データ」から取得したものを使用すること。**
**推測や創作した数字を使用した場合、その分析は無効となります。**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【○：判定ランク】銘柄名（証券コード）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 結論（3行以内）
（なぜこのランクなのか、最も重要な理由を端的に。**提供データに基づく事実のみ記載**）

■ 強制判定ルール該当チェック（**提供された実データのみで判定**）
□ ROE < 5% かつ PBR < 1.0 → 該当/非該当
□ ROE < 8%（株主資本コスト未満） → 該当/非該当
□ 売上成長率 > +35% → 該当/非該当
□ 営業CF < 0 → 該当/非該当
□ 有利子負債 > 純資産 → 該当/非該当

■ 5段階プロトコル結果サマリー
| Step | 判定 | 理由（1行） |
|------|------|-------------|
| Step1 トップライン | ○○ | ... |
| Step2 マルチプル | ○○ | ... |
| Step3 CF質 | ○○ | ... |
| Step4 機会費用 | ○○ | ... |
| Step5 出口戦略 | 設定済 | 損切○○%/利食○○% |

■ 各Step詳細分析
【Step1】...
【Step2】...
【Step3】...
【Step4】...
【Step5】...

■ リスク要因（必ず3つ以上列挙）
1. 
2. 
3. 

■ 推奨アクション
（明日ユーザーが取るべき具体的行動）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

---

## ■ セクター別補正基準

| セクター | 売上成長率基準 | 補足 |
|---------|---------------|------|
| 電力・ガス | +3%以上で合格 | 規制業種 |
| 銀行・保険 | +5%以上で合格 | 金利環境依存 |
| 不動産 | +5%以上で合格 | 賃貸は安定 |
| 鉄道・インフラ | +3%以上で合格 | 成熟産業 |
| 小売・外食 | +8%以上で合格 | 競争激化 |
| 製造業（一般） | +10%以上で合格 | 標準基準 |
| IT・SaaS | +15%以上で合格 | 高成長期待 |
| バイオ・創薬 | 赤字許容 | PSR、パイプラインで評価 |

---

## ■ 重要: 言語指定
**すべての分析結果は必ず日本語で記述してください。**
- 英語での出力は厳禁です
- 分析結果はMarkdown形式で、すべて日本語で回答してください。

---

**このプロンプトに従って、上記の銘柄データを分析せよ。**

**免責事項:** 投資判断は自己責任です。本分析は参考情報であり、投資を保証するものではありません。
"""

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        response_text = generate_with_fallback(prompt, api_key, model_name)

        # MarkdownをHTMLに変換
        html_content = markdown.markdown(response_text, extensions=['extra', 'nl2br', 'tables'])

        # スタイリッシュなHTMLラッパーを追加
        styled_html = f"""
        <style>
            .investment-analysis {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                line-height: 1.8;
                color: #e2e8f0;
            }}
            .investment-analysis h2 {{
                color: #818cf8;
                font-size: 1.5rem;
                font-weight: 700;
                margin: 2rem 0 1rem 0;
                padding-bottom: 0.5rem;
                border-bottom: 2px solid rgba(129, 140, 248, 0.3);
            }}
            .investment-analysis h3 {{
                color: #a5b4fc;
                font-size: 1.2rem;
                font-weight: 600;
                margin: 1.5rem 0 0.75rem 0;
            }}
            .investment-analysis h4 {{
                color: #c084fc;
                font-size: 1rem;
                font-weight: 600;
                margin: 1rem 0 0.5rem 0;
            }}
            .investment-analysis p {{
                margin: 0.75rem 0;
                color: #cbd5e1;
            }}
            .investment-analysis strong {{
                color: #f8fafc;
                font-weight: 600;
            }}
            .investment-analysis em {{
                color: #fbbf24;
                font-style: normal;
            }}
            .investment-analysis ul, .investment-analysis ol {{
                margin: 0.75rem 0;
                padding-left: 1.5rem;
            }}
            .investment-analysis li {{
                margin: 0.5rem 0;
                color: #cbd5e1;
            }}
            .investment-analysis table {{
                width: 100%;
                border-collapse: collapse;
                margin: 1.5rem 0;
                background: rgba(30, 41, 59, 0.5);
                border-radius: 8px;
                overflow: hidden;
            }}
            .investment-analysis th {{
                background: linear-gradient(135deg, rgba(129, 140, 248, 0.2), rgba(192, 132, 252, 0.2));
                color: #a5b4fc;
                padding: 0.75rem 1rem;
                text-align: left;
                font-weight: 600;
                font-size: 0.9rem;
            }}
            .investment-analysis td {{
                padding: 0.75rem 1rem;
                border-top: 1px solid rgba(148, 163, 184, 0.2);
                color: #cbd5e1;
            }}
            .investment-analysis tr:hover {{
                background: rgba(129, 140, 248, 0.05);
            }}
            .investment-analysis code {{
                background: rgba(129, 140, 248, 0.1);
                color: #818cf8;
                padding: 0.2rem 0.4rem;
                border-radius: 4px;
                font-family: 'Fira Code', monospace;
                font-size: 0.9em;
            }}
            .investment-analysis pre {{
                background: rgba(15, 23, 42, 0.8);
                border: 1px solid rgba(129, 140, 248, 0.2);
                border-radius: 8px;
                padding: 1rem;
                overflow-x: auto;
                margin: 1rem 0;
            }}
            .investment-analysis blockquote {{
                border-left: 4px solid #818cf8;
                padding-left: 1rem;
                margin: 1rem 0;
                color: #94a3b8;
                font-style: italic;
            }}
            .investment-analysis hr {{
                border: none;
                border-top: 1px solid rgba(148, 163, 184, 0.2);
                margin: 2rem 0;
            }}
            /* ランク別カラーリング */
            .investment-analysis :is(h2, h3):has(+ *:contains("【S")) {{
                color: #fbbf24;
            }}
            .investment-analysis :is(h2, h3):has(+ *:contains("【A")) {{
                color: #10b981;
            }}
            .investment-analysis :is(h2, h3):has(+ *:contains("【B")) {{
                color: #818cf8;
            }}
            .investment-analysis :is(h2, h3):has(+ *:contains("【C")) {{
                color: #f59e0b;
            }}
            .investment-analysis :is(h2, h3):has(+ *:contains("【D")) {{
                color: #ef4444;
            }}
        </style>
        <div class="investment-analysis">
            {html_content}
        </div>
        """

        return styled_html
    except Exception as e:
        logger.error(f"Investment analysis failed: {e}")
        return f"<p class='error' style='color: #fb7185;'>投資判断分析エラー: {str(e)}</p>"
