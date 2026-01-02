"""
高度な財務指標の計算
PEGレシオ、YoY/QoQ成長率、ROE、ROICなどを計算
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def calculate_yoy_growth(current: float, previous: float) -> Optional[float]:
    """
    YoY（前年比）成長率を計算

    Args:
        current: 当期の値
        previous: 前期の値

    Returns:
        成長率（%）、計算できない場合はNone
    """
    if previous is None or previous == 0 or current is None:
        return None

    try:
        growth = ((current - previous) / abs(previous)) * 100
        return round(growth, 2)
    except Exception as e:
        logger.error(f"YoY calculation error: {e}")
        return None


def calculate_peg_ratio(per: float, eps_growth_rate: float) -> Optional[float]:
    """
    PEGレシオを計算

    Args:
        per: 株価収益率
        eps_growth_rate: EPS成長率（%）

    Returns:
        PEGレシオ、計算できない場合はNone
    """
    if per is None or eps_growth_rate is None or eps_growth_rate == 0:
        return None

    try:
        peg = per / eps_growth_rate
        return round(peg, 2)
    except Exception as e:
        logger.error(f"PEG calculation error: {e}")
        return None


def calculate_roe(net_income: float, shareholders_equity: float) -> Optional[float]:
    """
    ROE（自己資本利益率）を計算

    Args:
        net_income: 純利益
        shareholders_equity: 自己資本（株主資本）

    Returns:
        ROE（%）、計算できない場合はNone
    """
    if net_income is None or shareholders_equity is None or shareholders_equity == 0:
        return None

    try:
        roe = (net_income / shareholders_equity) * 100
        return round(roe, 2)
    except Exception as e:
        logger.error(f"ROE calculation error: {e}")
        return None


def calculate_roic(nopat: float, invested_capital: float) -> Optional[float]:
    """
    ROIC（投下資本利益率）を計算

    Args:
        nopat: 税引後営業利益（Net Operating Profit After Tax）
        invested_capital: 投下資本

    Returns:
        ROIC（%）、計算できない場合はNone
    """
    if nopat is None or invested_capital is None or invested_capital == 0:
        return None

    try:
        roic = (nopat / invested_capital) * 100
        return round(roic, 2)
    except Exception as e:
        logger.error(f"ROIC calculation error: {e}")
        return None


def calculate_nopat(operating_income: float, tax_rate: float = 0.30) -> Optional[float]:
    """
    NOPAT（税引後営業利益）を計算

    Args:
        operating_income: 営業利益
        tax_rate: 実効税率（デフォルト30%）

    Returns:
        NOPAT、計算できない場合はNone
    """
    if operating_income is None:
        return None

    try:
        nopat = operating_income * (1 - tax_rate)
        return nopat
    except Exception as e:
        logger.error(f"NOPAT calculation error: {e}")
        return None


def calculate_invested_capital(total_assets: float, current_liabilities: float) -> Optional[float]:
    """
    投下資本を計算（簡易版）
    投下資本 = 総資産 - 流動負債

    Args:
        total_assets: 総資産
        current_liabilities: 流動負債

    Returns:
        投下資本、計算できない場合はNone
    """
    if total_assets is None or current_liabilities is None:
        return None

    try:
        invested_capital = total_assets - current_liabilities
        return invested_capital
    except Exception as e:
        logger.error(f"Invested Capital calculation error: {e}")
        return None


def analyze_advanced_metrics(ticker_obj: Any) -> Dict[str, Any]:
    """
    高度な財務指標を分析

    Args:
        ticker_obj: yfinance Tickerオブジェクト

    Returns:
        指標の辞書
    """
    results = {
        "peg_ratio": None,
        "roe_history": [],
        "roic_history": [],
        "revenue_yoy_history": [],
        "eps_yoy_history": [],
        "latest_roe": None,
        "latest_roic": None,
        "latest_revenue_yoy": None,
        "latest_eps_yoy": None
    }

    try:
        # 損益計算書データ取得
        income_stmt = ticker_obj.financials
        if income_stmt.empty:
            return results

        # 貸借対照表データ取得
        balance_sheet = ticker_obj.balance_sheet

        # データを転置して時系列順に並べる
        df_income = income_stmt.transpose().sort_index(ascending=True)
        df_balance = balance_sheet.transpose().sort_index(ascending=True) if not balance_sheet.empty else pd.DataFrame()

        # キーの取得（yfinanceのキー名は変動する可能性があるため）
        revenue_key = next((k for k in ["Total Revenue", "Operating Revenue"] if k in df_income.columns), None)
        net_income_key = next((k for k in ["Net Income", "Net Income Common Stockholders"] if k in df_income.columns), None)
        operating_income_key = next((k for k in ["Operating Income", "EBIT"] if k in df_income.columns), None)
        eps_key = next((k for k in ["Basic EPS", "Diluted EPS"] if k in df_income.columns), None)

        equity_key = next((k for k in ["Stockholders Equity", "Total Equity Gross Minority Interest", "Shareholders Equity"] if k in df_balance.columns), None) if not df_balance.empty else None
        total_assets_key = next((k for k in ["Total Assets"] if k in df_balance.columns), None) if not df_balance.empty else None
        current_liabilities_key = next((k for k in ["Current Liabilities"] if k in df_balance.columns), None) if not df_balance.empty else None

        # YoY成長率の計算（売上高・EPS）
        if revenue_key:
            revenue_values = df_income[revenue_key].dropna()
            for i in range(1, len(revenue_values)):
                yoy = calculate_yoy_growth(revenue_values.iloc[i], revenue_values.iloc[i-1])
                if yoy is not None:
                    results["revenue_yoy_history"].append({
                        "year": revenue_values.index[i].strftime("%Y") if hasattr(revenue_values.index[i], 'strftime') else str(revenue_values.index[i])[:4],
                        "yoy": yoy
                    })

            # 最新のYoY
            if len(results["revenue_yoy_history"]) > 0:
                results["latest_revenue_yoy"] = results["revenue_yoy_history"][-1]["yoy"]

        if eps_key:
            eps_values = df_income[eps_key].dropna()
            for i in range(1, len(eps_values)):
                yoy = calculate_yoy_growth(eps_values.iloc[i], eps_values.iloc[i-1])
                if yoy is not None:
                    results["eps_yoy_history"].append({
                        "year": eps_values.index[i].strftime("%Y") if hasattr(eps_values.index[i], 'strftime') else str(eps_values.index[i])[:4],
                        "yoy": yoy
                    })

            if len(results["eps_yoy_history"]) > 0:
                results["latest_eps_yoy"] = results["eps_yoy_history"][-1]["yoy"]

        # ROEの計算
        if net_income_key and equity_key:
            net_income_values = df_income[net_income_key].dropna()
            equity_values = df_balance[equity_key].dropna()

            # 共通の期間を取得
            common_dates = net_income_values.index.intersection(equity_values.index)

            for date in common_dates:
                roe = calculate_roe(net_income_values[date], equity_values[date])
                if roe is not None:
                    results["roe_history"].append({
                        "year": date.strftime("%Y") if hasattr(date, 'strftime') else str(date)[:4],
                        "roe": roe
                    })

            if len(results["roe_history"]) > 0:
                results["latest_roe"] = results["roe_history"][-1]["roe"]

        # ROICの計算
        if operating_income_key and total_assets_key and current_liabilities_key:
            operating_income_values = df_income[operating_income_key].dropna()
            total_assets_values = df_balance[total_assets_key].dropna()
            current_liabilities_values = df_balance[current_liabilities_key].dropna()

            common_dates = operating_income_values.index.intersection(
                total_assets_values.index.intersection(current_liabilities_values.index)
            )

            for date in common_dates:
                nopat = calculate_nopat(operating_income_values[date])
                invested_capital = calculate_invested_capital(
                    total_assets_values[date],
                    current_liabilities_values[date]
                )
                roic = calculate_roic(nopat, invested_capital)

                if roic is not None:
                    results["roic_history"].append({
                        "year": date.strftime("%Y") if hasattr(date, 'strftime') else str(date)[:4],
                        "roic": roic
                    })

            if len(results["roic_history"]) > 0:
                results["latest_roic"] = results["roic_history"][-1]["roic"]

        # PEGレシオの計算
        try:
            info = ticker_obj.info
            per = info.get('trailingPE') or info.get('forwardPE')

            # EPS CAGRを計算（3年）
            if eps_key and len(df_income[eps_key].dropna()) >= 4:
                eps_values = df_income[eps_key].dropna()
                start_eps = eps_values.iloc[-4]
                end_eps = eps_values.iloc[-1]

                if start_eps > 0 and end_eps > 0:
                    eps_cagr = ((end_eps / start_eps) ** (1/3) - 1) * 100
                    results["peg_ratio"] = calculate_peg_ratio(per, eps_cagr)
        except Exception as e:
            logger.error(f"PEG ratio calculation failed: {e}")

    except Exception as e:
        logger.error(f"Advanced metrics analysis failed: {e}")

    return results
