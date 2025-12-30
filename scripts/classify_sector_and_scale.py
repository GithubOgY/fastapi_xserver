from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os
import yfinance as yf
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Company, DATABASE_URL

load_dotenv()

def get_market_cap_category(market_cap):
    if not market_cap:
        return "不明"
    
    # 単位: 円
    # 大型: 3000億円以上
    # 中型: 300億円以上 3000億円未満
    # 小型: 300億円未満
    
    cap_oku = market_cap / 100000000
    
    if cap_oku >= 3000:
        return "大型株"
    elif cap_oku >= 300:
        return "中型株"
    else:
        return "小型株"

def classify_sector_and_scale():
    # Setup DB
    print(f"Connecting to: {DATABASE_URL}")
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL)
    
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Fetch 5 companies from different sectors for demonstration
        sectors = ["情報･通信業", "電気機器", "食料品", "銀行業"]
        target_companies = []
        
        for sec in sectors:
            # Fetch random 3 companies from each sector
            # Using order by random is DB specific, let's just take first few offsets
            comps = session.query(Company).filter(Company.sector_33 == sec).limit(3).all()
            target_companies.extend(comps)

        if not target_companies:
            print("No companies found.")
            return

        print(f"\nAnalyzing {len(target_companies)} companies for Sector x Scale classification...\n")
        print(f"{'コード':<6} | {'社名':<20} | {'業種':<12} | {'時価総額':<10} | {'規模分類'}")
        print("-" * 70)

        for comp in target_companies:
            ticker = f"{comp.code_4digit}.T"
            try:
                # Use yfinance to get market cap
                stock = yf.Ticker(ticker)
                info = stock.info
                market_cap = info.get("marketCap", 0)
                
                scale = get_market_cap_category(market_cap)
                
                # Format market cap for display
                if market_cap:
                    cap_display = f"{market_cap / 100000000:.1f}億円"
                else:
                    cap_display = "-"
                    scale = "取得不可"
                
                print(f"{comp.code_4digit:<6} | {comp.name[:20]:<20} | {comp.sector_33[:10]:<12} | {cap_display:<10} | {scale}")
                
            except Exception as e:
                print(f"{comp.code_4digit:<6} | {comp.name[:20]:<20} | Error: {e}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    classify_sector_and_scale()
