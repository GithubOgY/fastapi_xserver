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


def get_investment_data(code: str) -> dict:
    """
    投資判断に必要な包括的なデータを取得
    Returns a dict with valuation, financial metrics, and market data
    """
    data = {}
    if not code:
        return data

    try:
        # Format code: 1234 -> 1234.T
        ticker_symbol = code
        if len(code) == 4:
            ticker_symbol = f"{code}.T"
        elif len(code) == 5 and code.endswith("0"):
             ticker_symbol = f"{code[:4]}.T"
        elif not code.endswith(".T"):
             if code.isdigit():
                 ticker_symbol = f"{code}.T"

        stock = yf.Ticker(ticker_symbol)
        info = stock.info

        if not info:
             return data

        # === S優先度: 銘柄特定 ===
        data["銘柄名"] = info.get("longName") or info.get("shortName", "")
        data["証券コード"] = code

        # === S優先度: バリュエーション ===
        data["株価"] = info.get("currentPrice") or info.get("regularMarketPrice")
        data["時価総額"] = info.get("marketCap")
        data["PER"] = info.get("trailingPE") or info.get("forwardPE")
        data["PBR"] = info.get("priceToBook")

        # === S優先度: 資本効率 ===
        if "returnOnEquity" in info and info["returnOnEquity"]:
            data["ROE"] = round(info["returnOnEquity"] * 100, 2)
        if "returnOnAssets" in info and info["returnOnAssets"]:
            data["ROA"] = round(info["returnOnAssets"] * 100, 2)

        # === A優先度: 財務健全性 ===
        # 自己資本比率の計算
        total_equity = info.get("totalStockholderEquity")
        total_assets = info.get("totalAssets")
        if total_equity and total_assets and total_assets > 0:
            data["自己資本比率"] = round((total_equity / total_assets) * 100, 2)

        # ネットキャッシュ
        cash = info.get("totalCash", 0)
        debt = info.get("totalDebt", 0)
        data["ネットキャッシュ"] = cash - debt
        data["現金及び現金同等物"] = cash
        data["有利子負債"] = debt

        # === A優先度: 成長性 ===
        data["売上成長率"] = info.get("revenueGrowth")
        data["利益成長率"] = info.get("earningsGrowth")

        # === A優先度: 将来性 ===
        data["アナリスト目標株価"] = info.get("targetMeanPrice")
        data["アナリスト推奨"] = info.get("recommendationKey")

        # === B優先度: 株主還元 ===
        data["配当利回り"] = info.get("dividendYield")
        data["配当性向"] = info.get("payoutRatio")

        # === B優先度: 従業員 ===
        data["従業員数"] = info.get("fullTimeEmployees")

        # === その他の有用な情報 ===
        data["52週高値"] = info.get("fiftyTwoWeekHigh")
        data["52週安値"] = info.get("fiftyTwoWeekLow")
        data["業種"] = info.get("sector")
        data["セクター"] = info.get("industry")

    except Exception as e:
        logger.warning(f"Failed to fetch investment data for {code}: {e}")

    return data
