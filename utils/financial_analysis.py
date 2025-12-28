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
        Dictionary of growth rates (percentage)
    """
    growth_rates = {}
    
    metrics = [
        "売上高", "営業利益", "経常利益", "当期純利益", 
        "EPS", "営業CF", "純資産", "総資産"
    ]
    
    for metric in metrics:
        curr_val = current_data.get(metric)
        prev_val = previous_data.get(metric)
        
        if curr_val is not None and prev_val is not None and prev_val != 0:
            # Check if values are numbers
            if isinstance(curr_val, (int, float)) and isinstance(prev_val, (int, float)):
                growth = ((curr_val - prev_val) / abs(prev_val)) * 100
                growth_rates[f"{metric}_成長率"] = round(growth, 2)
            else:
                growth_rates[f"{metric}_成長率"] = None
        else:
            growth_rates[f"{metric}_成長率"] = None
            
    return growth_rates

def calculate_profitability_metrics(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate profitability ratios.
    
    Returns:
        Dictionary of profitability ratios (percentage)
    """
    metrics = {}
    
    sales = data.get("売上高")
    op_income = data.get("営業利益")
    ord_income = data.get("経常利益")
    net_income = data.get("当期純利益")
    equity = data.get("純資産")
    assets = data.get("総資産")
    
    # Margins
    if sales and sales != 0:
        if isinstance(op_income, (int, float)):
            metrics["営業利益率"] = round((op_income / sales) * 100, 2)
        if isinstance(ord_income, (int, float)):
            metrics["経常利益率"] = round((ord_income / sales) * 100, 2)
        if isinstance(net_income, (int, float)):
            metrics["純利益率"] = round((net_income / sales) * 100, 2)
            
    # Returns
    if net_income and isinstance(net_income, (int, float)):
        if equity and equity != 0 and isinstance(equity, (int, float)):
            metrics["ROE"] = round((net_income / equity) * 100, 2)
        if assets and assets != 0 and isinstance(assets, (int, float)):
            metrics["ROA"] = round((net_income / assets) * 100, 2)
            
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

def calculate_efficiency_metrics(data: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate efficiency ratios.
    """
    metrics = {}
    
    sales = data.get("売上高")
    assets = data.get("総資産")
    receivables = data.get("受取手形及び売掛金") # Assuming this key exists or is mapped
    inventory = data.get("棚卸資産") # Assuming this key exists or is mapped
    
    # Asset Turnover
    if sales and assets and assets != 0:
        if isinstance(sales, (int, float)) and isinstance(assets, (int, float)):
            metrics["総資産回転率"] = round(sales / assets, 2)
            
    return metrics

def analyze_company_performance(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze company performance over the available history.
    
    Args:
        history: List of historical data dictionaries (should be sorted by date)
        
    Returns:
        Dictionary containing comprehensive analysis
    """
    if not history:
        return {}
        
    # Sort just in case (oldest to newest)
    sorted_history = sorted(history, key=lambda x: x["metadata"].get("period_end", ""))
    
    latest = sorted_history[-1].get("normalized_data", {})
    prev = sorted_history[-2].get("normalized_data", {}) if len(sorted_history) > 1 else {}
    
    # 1. Basic Metrics (Latest)
    analysis = {
        "latest_period": sorted_history[-1]["metadata"].get("period_end"),
        "profitability": calculate_profitability_metrics(latest),
        "safety": calculate_safety_metrics(latest),
        "efficiency": calculate_efficiency_metrics(latest),
    }
    
    # 2. Growth Rates (Latest vs Previous)
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
