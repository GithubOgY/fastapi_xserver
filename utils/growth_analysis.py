
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

def calculate_cagr(start_val: float, end_val: float, periods: int) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate (CAGR).
    Formula: (End / Start) ^ (1 / n) - 1
    """
    if start_val <= 0 or end_val <= 0 or periods <= 0:
        return None
    try:
        cagr = (end_val / start_val) ** (1 / periods) - 1
        return round(cagr * 100, 2)
    except Exception as e:
        logger.error(f"CAGR calculation error: {e}")
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
                results["revenue_cagr_3y"] = calculate_cagr(start_val, end_val, 3)

                if op_key and len(vals_op) >= 4:
                    results["op_income_cagr_3y"] = calculate_cagr(vals_op.iloc[-4], vals_op.iloc[-1], 3)
                if eps_key and len(vals_eps) >= 4:
                    results["eps_cagr_3y"] = calculate_cagr(vals_eps.iloc[-4], vals_eps.iloc[-1], 3)

            # 5年CAGR計算
            # 必要データ: 6つのデータポイント (Year 0, 1, 2, 3, 4, 5)
            # 計算: (Year5 / Year0)^(1/5) - 1
            if n >= 6:
                start_val = vals_rev.iloc[-6]  # 5年前 (Year 0)
                end_val = latest_rev           # 最新年 (Year 5)
                results["revenue_cagr_5y"] = calculate_cagr(start_val, end_val, 5)

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

        # Margin Trend (3年間のトレンド分析)
        if rev_key and op_key:
            margins = (df[op_key] / df[rev_key]).dropna()
            if len(margins) >= 3:
                # 直近3年の利益率を取得
                recent_margins = margins.iloc[-3:]

                # 線形回帰的なトレンド判定：最古と最新を比較
                oldest_margin = recent_margins.iloc[0]
                latest_margin = recent_margins.iloc[-1]

                # 3年間での変化率を計算
                margin_change = (latest_margin - oldest_margin) / oldest_margin if oldest_margin != 0 else 0

                if margin_change > 0.05:  # 5%以上改善
                    results["margin_trend"] = "improving"
                elif margin_change < -0.05:  # 5%以上悪化
                    results["margin_trend"] = "declining"
                else:
                    results["margin_trend"] = "stable"

    except Exception as e:
        logger.error(f"Growth analysis failed: {e}")

    return results
