import yfinance as yf
import logging

logger = logging.getLogger(__name__)

def get_financial_metrics(code: str) -> dict:
    """
    Fetch financial metrics from Yahoo Finance via yfinance.
    Returns a dict with keys compatible with EDINET normalized data.
    """
    metrics = {}
    if not code:
        return metrics
        
    try:
        # Format code: 1234 -> 1234.T
        ticker_symbol = code
        if len(code) == 4:
            ticker_symbol = f"{code}.T"
        elif len(code) == 5 and code.endswith("0"):
             ticker_symbol = f"{code[:4]}.T"
        elif not code.endswith(".T"):
             # Assuming JP stock if numeric
             if code.isdigit():
                 ticker_symbol = f"{code}.T"
        
        stock = yf.Ticker(ticker_symbol)
        info = stock.info
        
        if not info:
             return metrics

        # --- Extract Metrics ---
        
        # 売上高 (Total Revenue)
        if "totalRevenue" in info and info["totalRevenue"]:
            metrics["売上高"] = info["totalRevenue"]
            
        # 当期純利益 (Net Income)
        if "netIncomeToCommon" in info and info["netIncomeToCommon"]:
             metrics["当期純利益"] = info["netIncomeToCommon"]

        # 営業利益 (Operating Income) - info may assume TTM
        # Sometimes 'operatingIncome' key exists directly
        if "operatingIncome" in info and info["operatingIncome"]:
            metrics["営業利益"] = info["operatingIncome"]

        # ROE (Return on Equity) -> decimal
        if "returnOnEquity" in info and info["returnOnEquity"]:
             metrics["ROE"] = info["returnOnEquity"] * 100 # Convert to percentage value (e.g. 13.6)
             
        # ROA (Return on Assets) -> decimal
        if "returnOnAssets" in info and info["returnOnAssets"]:
             metrics["ROA"] = info["returnOnAssets"] * 100 # Convert to percentage value
             
        # 自己資本比率 (Equity Ratio) is not direct property
        # Calculation: Total Equity / Total Assets if available in fast info?
        # Often not in 'info' accurately. We can rely on EDINET for this mostly as BS is standard.
        # But let's check basic stats.
        
    except Exception as e:
        logger.warning(f"Failed to fetch yfinance data for {code}: {e}")
        
    return metrics
