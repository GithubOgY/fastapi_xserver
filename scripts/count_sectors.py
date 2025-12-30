from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import sys
import os

# Add parent directory to path to allow importing from database.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Company, DATABASE_URL

def count_sectors():
    # Setup DB connection
    print(f"Connecting to: {DATABASE_URL}")
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL)
    
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        print("\n--- Total Companies ---")
        total = session.query(Company).count()
        print(f"Total: {total}")

        print("\n--- Sector 33 Breakdown ---")
        # Direct SQL is often easier for group by aggregation if ORM is simple
        # But let's use ORM for consistency
        from sqlalchemy import func
        
        results_33 = session.query(
            Company.sector_33, func.count(Company.ticker)
        ).group_by(Company.sector_33).order_by(func.count(Company.ticker).desc()).all()
        
        for sector, count in results_33:
            sec_name = sector if sector else "Unknown/None"
            print(f"{sec_name}: {count}")

        print("\n--- Sector 17 Breakdown ---")
        results_17 = session.query(
            Company.sector_17, func.count(Company.ticker)
        ).group_by(Company.sector_17).order_by(func.count(Company.ticker).desc()).all()
        
        for sector, count in results_17:
            sec_name = sector if sector else "Unknown/None"
            print(f"{sec_name}: {count}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    count_sectors()
