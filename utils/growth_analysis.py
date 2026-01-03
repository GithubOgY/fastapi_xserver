
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Union
import logging

logger = logging.getLogger(__name__)

def calculate_cagr(start_val: float, end_val: float, periods: Union[int, float]) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate (CAGR).
    Formula: (End / Start) ^ (1 / n) - 1
    """
    if start_val <= 0 or end_val <= 0 or periods is None or periods <= 0:
        return None
    try:
        cagr = (end_val / start_val) ** (1 / periods) - 1
        return round(cagr * 100, 2)
    except Exception as e:
        logger.error(f"CAGR calculation error: {e}")
        return None


def _years_between(start_date, end_date) -> Optional[float]:
    """
    pandas.Timestamp / datetime などの差分から「年数（年換算）」を推定する。
    例：3年CAGRでも決算期変更等で厳密に3年でないケースを吸収するため。
    """
    try:
        if start_date is None or end_date is None:
            return None
        # pandas Timestampならto_pydatetimeがある
        if hasattr(start_date, "to_pydatetime"):
            start_date = start_date.to_pydatetime()
        if hasattr(end_date, "to_pydatetime"):
            end_date = end_date.to_pydatetime()
        delta_days = (end_date - start_date).days
        if delta_days <= 0:
            return None
        # 365.25で年換算
        return delta_days / 365.25
    except Exception:
        return None

def analyze_growth_quality(ticker_obj: Any) -> Dict[str, Any]:
    """
    Analyze growth quality and stability.
    Returns:
        Dictionary containing CAGR metrics and stability flags.
    """
    results = {
        "revenue_cagr_3y": None,
        "revenue_cagr_5y": None,
        "op_income_cagr_3y": None,
        "op_income_cagr_5y": None,
        "eps_cagr_3y": None,
        "eps_cagr_5y": None,
        "consecutive_growth_years": 0,
        "margin_trend": "stable",
        # 収益（利益率）の安定性判定（直近3年の営業利益率のブレ）
        # stable / moderate / volatile / unknown
        "profitability_stability": "unknown",
        # 補助情報（UI表示・デバッグ用）
        "margin_slope_pp_per_year": None,      # 傾き（%pt/年）
        "margin_std_pp_3y": None,              # 標準偏差（%pt）
        "is_high_growth": False,
        "history": [] # For charting
    }

    try:
        # Fetch annual financials
        fin = ticker_obj.financials # Annual Income Statement
        if fin.empty:
            return results

        # Transpose and sort by date (oldest to newest)
        df = fin.transpose().sort_index(ascending=True)
        
        # We need Revenue, Operating Income, and Basic EPS
        # Map indices (yfinance keys can vary)
        rev_key = next((k for k in ["Total Revenue", "Operating Revenue"] if k in df.columns), None)
        op_key = next((k for k in ["Operating Income", "Operating Profit"] if k in df.columns), None)
        eps_key = next((k for k in ["Basic EPS", "Earnings Per Share"] if k in df.columns), None)

        if not rev_key:
            return results

        # Prepare history for charting
        history_data = []
        for date, row in df.iterrows():
            rev_val = row.get(rev_key)
            op_val = row.get(op_key)
            history_data.append({
                "date": date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else str(date)[:10],
                "revenue": float(rev_val) if pd.notna(rev_val) else 0,
                "op_income": float(op_val) if pd.notna(op_val) else 0
            })
        results["history"] = history_data

        # Calculate CAGR
        vals_rev = df[rev_key].dropna()
        vals_op = df[op_key].dropna() if op_key else pd.Series()
        vals_eps = df[eps_key].dropna() if eps_key else pd.Series()

        n = len(vals_rev)
        if n >= 2:
            latest_rev = vals_rev.iloc[-1]

            # 3年CAGR計算
            # 必要データ: 4つのデータポイント (Year 0, 1, 2, 3)
            # 計算: (Year3 / Year0)^(1/3) - 1
            if n >= 4:
                start_val = vals_rev.iloc[-4]  # 3年前 (Year 0)
                end_val = latest_rev           # 最新年 (Year 3)
                # 決算期変更などのズレを吸収：日付差分から年数を推定（取れなければ3でフォールバック）
                start_date = vals_rev.index[-4] if hasattr(vals_rev, "index") else None
                end_date = vals_rev.index[-1] if hasattr(vals_rev, "index") else None
                years = _years_between(start_date, end_date) or 3
                results["revenue_cagr_3y"] = calculate_cagr(start_val, end_val, years)

                if op_key and len(vals_op) >= 4:
                    results["op_income_cagr_3y"] = calculate_cagr(vals_op.iloc[-4], vals_op.iloc[-1], years)
                if eps_key and len(vals_eps) >= 4:
                    results["eps_cagr_3y"] = calculate_cagr(vals_eps.iloc[-4], vals_eps.iloc[-1], years)

            # 5年CAGR計算
            # 必要データ: 6つのデータポイント (Year 0, 1, 2, 3, 4, 5)
            # 計算: (Year5 / Year0)^(1/5) - 1
            if n >= 6:
                start_val = vals_rev.iloc[-6]  # 5年前 (Year 0)
                end_val = latest_rev           # 最新年 (Year 5)
                start_date = vals_rev.index[-6] if hasattr(vals_rev, "index") else None
                end_date = vals_rev.index[-1] if hasattr(vals_rev, "index") else None
                years_5 = _years_between(start_date, end_date) or 5
                results["revenue_cagr_5y"] = calculate_cagr(start_val, end_val, years_5)

            # Check for high growth (Revenue CAGR > 10%)
            if results["revenue_cagr_3y"] and results["revenue_cagr_3y"] >= 10:
                results["is_high_growth"] = True

        # Consecutive growth years (Revenue)
        growth_count = 0
        for i in range(len(vals_rev) - 1, 0, -1):
            if vals_rev.iloc[i] > vals_rev.iloc[i-1]:
                growth_count += 1
            else:
                break
        results["consecutive_growth_years"] = growth_count

        # Margin Trend & Profitability Stability
        if rev_key and op_key:
            margins = (df[op_key] / df[rev_key]).dropna()
            if len(margins) >= 3:
                # 直近3年の利益率を取得
                recent_margins = margins.iloc[-3:]

                # -------- 利益率トレンド（%pt/年の傾きで判定） --------
                # 相対%だと「10%→9%」が-10%扱いで過敏になるため、%pt（ポイント）で判定する
                x = np.arange(len(recent_margins), dtype=float)  # [0,1,2]
                y = recent_margins.astype(float).to_numpy()      # 利益率（0.10等）
                slope = np.polyfit(x, y, 1)[0]                   # 1年あたりの傾き（ratio/年）
                slope_pp_per_year = slope * 100                  # %pt/年
                results["margin_slope_pp_per_year"] = round(slope_pp_per_year, 2)

                # 目安：±1.0%pt/年を超えたら明確な改善/悪化
                if slope_pp_per_year > 1.0:
                    results["margin_trend"] = "improving"
                elif slope_pp_per_year < -1.0:
                    results["margin_trend"] = "declining"
                else:
                    results["margin_trend"] = "stable"

                # -------- 収益安定性（直近3年のブレ：標準偏差） --------
                std_pp = float(np.std(y, ddof=0) * 100)  # %pt
                results["margin_std_pp_3y"] = round(std_pp, 2)

                # 目安：<=1.0%pt 安定、<=3.0%pt まあまあ、>3.0%pt ブレ大
                if std_pp <= 1.0:
                    results["profitability_stability"] = "stable"
                elif std_pp <= 3.0:
                    results["profitability_stability"] = "moderate"
                else:
                    results["profitability_stability"] = "volatile"

    except Exception as e:
        logger.error(f"Growth analysis failed: {e}")

    return results
