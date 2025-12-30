from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Company, DATABASE_URL

def count_scale():
    print(f"Connecting to: {DATABASE_URL}")
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL)
    
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        print("\n--- Scale Category Distribution ---")
        results = session.query(
            Company.scale_category, func.count(Company.ticker)
        ).group_by(Company.scale_category).order_by(func.count(Company.ticker).desc()).all()
        
        for cat, count in results:
            cat_name = cat if cat else "None"
            print(f"{cat_name}: {count}")

        # Cross analysis: Food Sector (Sector33='食料品') x Scale
        print("\n--- '食料品' Sector x Scale Breakdown ---")
        food_results = session.query(
            Company.scale_category, func.count(Company.ticker)
        ).filter(
            Company.sector_33 == '食料品'
        ).group_by(Company.scale_category).order_by(func.count(Company.ticker).desc()).all()
        
        for cat, count in food_results:
            cat_name = cat if cat else "None"
            print(f"{cat_name}: {count}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    count_scale()
