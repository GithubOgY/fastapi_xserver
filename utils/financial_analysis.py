"""
Financial Analysis Utilities

This module provides functions to calculate various financial ratios and metrics
based on EDINET financial data and market data (Yahoo Finance).
"""

from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

def calculate_growth_rates(current_data: Dict[str, Any], previous_data: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate Year-over-Year (YoY) growth rates for key metrics.

    Args:
        current_data: Normalized financial data for the current period
        previous_data: Normalized financial data for the previous period

    Returns:
        Dictionary of growth rates (percentage) and status flags

    Notes:
        - Standard growth rate: ((Current - Previous) / |Previous|) × 100
        - Special cases handled:
          1. Previous = 0: Cannot calculate (returns None)
          2. Previous < 0, Current > 0: "黒字転換" (turned profitable)
          3. Previous > 0, Current < 0: "赤字転落" (turned to loss)
          4. Both negative: Growth rate may be misleading, flagged as "要注意"
    """
    growth_rates = {}

    metrics = [
        "売上高", "営業利益", "経常利益", "当期純利益",
        "EPS", "営業CF", "純資産", "総資産"
    ]

    for metric in metrics:
        curr_val = current_data.get(metric)
        prev_val = previous_data.get(metric)

        # Skip if either value is missing
        if curr_val is None or prev_val is None:
            growth_rates[f"{metric}_成長率"] = None
            continue

        # Check if values are numbers
        if not (isinstance(curr_val, (int, float)) and isinstance(prev_val, (int, float))):
            growth_rates[f"{metric}_成長率"] = None
            continue

        # Case 1: Previous value is zero - cannot calculate growth rate
        if prev_val == 0:
            growth_rates[f"{metric}_成長率"] = None
            growth_rates[f"{metric}_成長率_備考"] = "前期ゼロのため計算不可"
            continue

        # Case 2: Sign change from negative to positive (turned profitable)
        if prev_val < 0 and curr_val >= 0:
            growth_rates[f"{metric}_成長率"] = None
            growth_rates[f"{metric}_成長率_備考"] = "黒字転換"
            growth_rates[f"{metric}_前期"] = prev_val
            growth_rates[f"{metric}_当期"] = curr_val
            continue

        # Case 3: Sign change from positive to negative (turned to loss)
        if prev_val > 0 and curr_val < 0:
            growth_rates[f"{metric}_成長率"] = None
            growth_rates[f"{metric}_成長率_備考"] = "赤字転落"
            growth_rates[f"{metric}_前期"] = prev_val
            growth_rates[f"{metric}_当期"] = curr_val
            continue

        # Case 4: Both negative - growth rate is misleading
        if prev_val < 0 and curr_val < 0:
            # Calculate but flag as potentially misleading
            growth = ((curr_val - prev_val) / abs(prev_val)) * 100
            growth_rates[f"{metric}_成長率"] = round(growth, 2)
            growth_rates[f"{metric}_成長率_備考"] = "両期とも赤字（解釈に注意）"
            continue

        # Standard case: both values have same sign (both positive or both zero-excluded)
        growth = ((curr_val - prev_val) / abs(prev_val)) * 100
        growth_rates[f"{metric}_成長率"] = round(growth, 2)

    return growth_rates

def calculate_profitability_metrics(data: Dict[str, Any], previous_data: Dict[str, Any] = None) -> Dict[str, float]:
    """
    Calculate profitability ratios.

    Args:
        data: Current period financial data
        previous_data: Previous period financial data (for period-average calculations)

    Returns:
        Dictionary of profitability ratios (percentage)

    Notes:
        - ROE and ROA use period-average equity/assets when previous data is available
        - This provides more accurate representation as these balances change throughout the period
    """
    metrics = {}

    sales = data.get("売上高")
    op_income = data.get("営業利益")
    ord_income = data.get("経常利益")
    net_income = data.get("当期純利益")
    equity = data.get("純資産")
    assets = data.get("総資産")

    # Margins (no change needed - these use P/L items)
    if sales and sales != 0:
        if isinstance(op_income, (int, float)):
            metrics["営業利益率"] = round((op_income / sales) * 100, 2)
        if isinstance(ord_income, (int, float)):
            metrics["経常利益率"] = round((ord_income / sales) * 100, 2)
        if isinstance(net_income, (int, float)):
            metrics["純利益率"] = round((net_income / sales) * 100, 2)

    # Returns - Use period average for balance sheet items
    if net_income and isinstance(net_income, (int, float)):
        # ROE - Use average equity if previous data available
        if equity and equity != 0 and isinstance(equity, (int, float)):
            if previous_data:
                prev_equity = previous_data.get("純資産")
                if prev_equity and isinstance(prev_equity, (int, float)) and prev_equity != 0:
                    avg_equity = (equity + prev_equity) / 2
                    if avg_equity != 0:
                        metrics["ROE"] = round((net_income / avg_equity) * 100, 2)
                        metrics["ROE_計算方法"] = "期間平均"
                else:
                    # Previous equity not available, use period-end
                    metrics["ROE"] = round((net_income / equity) * 100, 2)
                    metrics["ROE_計算方法"] = "期末時点"
            else:
                # No previous data, use period-end
                metrics["ROE"] = round((net_income / equity) * 100, 2)
                metrics["ROE_計算方法"] = "期末時点"

        # ROA - Use average assets if previous data available
        if assets and assets != 0 and isinstance(assets, (int, float)):
            if previous_data:
                prev_assets = previous_data.get("総資産")
                if prev_assets and isinstance(prev_assets, (int, float)) and prev_assets != 0:
                    avg_assets = (assets + prev_assets) / 2
                    if avg_assets != 0:
                        metrics["ROA"] = round((net_income / avg_assets) * 100, 2)
                        metrics["ROA_計算方法"] = "期間平均"
                else:
                    # Previous assets not available, use period-end
                    metrics["ROA"] = round((net_income / assets) * 100, 2)
                    metrics["ROA_計算方法"] = "期末時点"
            else:
                # No previous data, use period-end
                metrics["ROA"] = round((net_income / assets) * 100, 2)
                metrics["ROA_計算方法"] = "期末時点"

    return metrics

def calculate_safety_metrics(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate safety/stability ratios.
    """
    metrics = {}
    
    equity = data.get("純資産")
    assets = data.get("総資産")
    current_assets = data.get("流動資産")
    current_liabilities = data.get("流動負債")
    
    # Equity Ratio (Capital Adequacy Ratio)
    if equity and assets and assets != 0:
        if isinstance(equity, (int, float)) and isinstance(assets, (int, float)):
            metrics["自己資本比率"] = round((equity / assets) * 100, 2)
            
    # Current Ratio
    if current_assets and current_liabilities and current_liabilities != 0:
        if isinstance(current_assets, (int, float)) and isinstance(current_liabilities, (int, float)):
            metrics["流動比率"] = round((current_assets / current_liabilities) * 100, 2)
            
    return metrics

def calculate_efficiency_metrics(data: Dict[str, Any], previous_data: Dict[str, Any] = None) -> Dict[str, float]:
    """
    Calculate efficiency ratios.

    Args:
        data: Current period financial data
        previous_data: Previous period financial data (for period-average calculations)

    Returns:
        Dictionary of efficiency ratios

    Notes:
        - Asset turnover uses period-average assets for more accurate calculation
        - Turnover ratios measure how efficiently a company uses its assets
    """
    metrics = {}

    sales = data.get("売上高")
    assets = data.get("総資産")
    receivables = data.get("受取手形及び売掛金")  # Assuming this key exists or is mapped
    inventory = data.get("棚卸資産")  # Assuming this key exists or is mapped

    # Asset Turnover - Use average assets if previous data available
    if sales and assets and assets != 0:
        if isinstance(sales, (int, float)) and isinstance(assets, (int, float)):
            if previous_data:
                prev_assets = previous_data.get("総資産")
                if prev_assets and isinstance(prev_assets, (int, float)) and prev_assets != 0:
                    avg_assets = (assets + prev_assets) / 2
                    if avg_assets != 0:
                        metrics["総資産回転率"] = round(sales / avg_assets, 2)
                        metrics["総資産回転率_計算方法"] = "期間平均"
                else:
                    # Previous assets not available, use period-end
                    metrics["総資産回転率"] = round(sales / assets, 2)
                    metrics["総資産回転率_計算方法"] = "期末時点"
            else:
                # No previous data, use period-end
                metrics["総資産回転率"] = round(sales / assets, 2)
                metrics["総資産回転率_計算方法"] = "期末時点"

    return metrics

def analyze_company_performance(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze company performance over the available history.

    Args:
        history: List of historical data dictionaries (should be sorted by date)

    Returns:
        Dictionary containing comprehensive analysis with improved accuracy:
        - Profitability metrics (ROE, ROA) using period-average method
        - Efficiency metrics (turnover ratios) using period-average method
        - Growth rates with special case handling (黒字転換, 赤字転落, etc.)
        - Trend analysis for long-term performance evaluation

    Notes:
        - Requires at least 1 period for basic metrics
        - Requires at least 2 periods for growth rates and period-average calculations
        - Requires at least 3 periods for trend analysis
    """
    if not history:
        return {}

    # Sort just in case (oldest to newest)
    sorted_history = sorted(history, key=lambda x: x["metadata"].get("period_end", ""))

    latest = sorted_history[-1].get("normalized_data", {})
    prev = sorted_history[-2].get("normalized_data", {}) if len(sorted_history) > 1 else {}

    # 1. Basic Metrics (Latest) - Use period-average if previous data available
    analysis = {
        "latest_period": sorted_history[-1]["metadata"].get("period_end"),
        "profitability": calculate_profitability_metrics(latest, prev if prev else None),
        "safety": calculate_safety_metrics(latest),
        "efficiency": calculate_efficiency_metrics(latest, prev if prev else None),
    }

    # 2. Growth Rates (Latest vs Previous) - Now includes special case handling
    if prev:
        analysis["growth_yoy"] = calculate_growth_rates(latest, prev)
        
    # 3. Trends (Linear Regression Slope for key metrics)
    if len(sorted_history) >= 3:
        trends = {}
        for metric in ["売上高", "営業利益", "EPS"]:
            values = []
            for h in sorted_history:
                val = h.get("normalized_data", {}).get(metric)
                if isinstance(val, (int, float)):
                    values.append(val)
            
            if len(values) >= 3:
                # Simple slope calculation (change per period)
                x = np.arange(len(values))
                y = np.array(values)
                slope, _ = np.polyfit(x, y, 1)
                
                # Normalize slope as percentage of average
                avg = np.mean(y)
                if avg != 0:
                    trend_pct = (slope / avg) * 100
                    trends[metric] = {
                        "slope": slope,
                        "trend_pct": round(trend_pct, 2),
                        "direction": "up" if slope > 0 else "down"
                    }
        analysis["trends"] = trends
        
    return analysis
