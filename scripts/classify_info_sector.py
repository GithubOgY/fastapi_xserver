from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Company, DATABASE_URL
from utils.ai_analysis import generate_with_fallback

load_dotenv()

def classify_info_sector():
    # Setup DB
    print(f"Connecting to: {DATABASE_URL}")
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL)
    
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Fetch up to 15 companies from "情報・通信業"
        # Since DB stores strings, we need to match exactly or using LIKE
        # In count_sectors, we saw "情報･通信業" (note the half-width dot potentially?)
        # Let's try flexible query
        companies = session.query(Company).filter(
            Company.sector_33.like("%通信%")
        ).limit(15).all()

        if not companies:
            print("No companies found with sector '情報・通信業'")
            return

        print(f"\nFound {len(companies)} companies. Starting AI classification...\n")

        # Prepare list for AI
        company_list_str = "\n".join([f"- {c.name} ({c.code_4digit})" for c in companies])

        # Prompt for Gemini
        prompt = f"""
        以下の日本の「情報・通信業」に属する企業のリストについて、
        それぞれの詳細なサブセクター（業態）を推定して分類してください。

        分類のカテゴリ例:
        - 携帯キャリア
        - SIer（システムインテグレーター）
        - ゲーム開発
        - Webサービス/Eコマース
        - メディア/放送
        - SaaS/ソフトウェア
        - 半導体関連
        - その他

        ## 対象企業
        {company_list_str}

        ## 出力フォーマット
        | 証券コード | 企業名 | AI推定サブセクター | 一言解説 |
        | --- | --- | --- | --- |
        (各企業について1行ずつ)
        """

        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        
        if not api_key:
            print("Error: GEMINI_API_KEY not set.")
            return

        print("Waiting for Gemini response...")
        response_text = generate_with_fallback(prompt, api_key, model)
        
        print("\n=== AI Classification Result ===\n")
        print(response_text)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    classify_info_sector()
