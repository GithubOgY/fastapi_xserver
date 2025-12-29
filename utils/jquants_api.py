import requests
import os
import time
from sqlalchemy.orm import Session
from database import Company, SessionLocal
from datetime import datetime, date
import logging
from dotenv import load_dotenv

# Ensure env is loaded
load_dotenv()

# Check for API Key in environment
API_KEY = os.getenv("JQUANTS_API_KEY")

logger = logging.getLogger("uvicorn")

def fetch_all_listed_companies():
    """
    Fetch all listed companies from J-Quants API v2 (/equities/master).
    Handles pagination automatically.
    """
    if not API_KEY:
        logger.error("JQUANTS_API_KEY is not set.")
        raise ValueError("JQUANTS_API_KEY is missing")

    url = "https://api.jquants.com/v2/equities/master"
    headers = {"x-api-key": API_KEY}
    params = {}
    
    all_data = []
    
    try:
        logger.info("[J-Quants] Fetching listed companies (v2)...")
        while True:
            res = requests.get(url, params=params, headers=headers)
            res.raise_for_status()
            
            d = res.json()
            data_chunk = d.get("data", [])
            all_data.extend(data_chunk)
            
            pagination_key = d.get("pagination_key")
            if pagination_key:
                params["pagination_key"] = pagination_key
                time.sleep(1)
                logger.info(f"[J-Quants] Fetching next page... (Total so far: {len(all_data)})")
            else:
                break
                
        logger.info(f"[J-Quants] Total companies fetched: {len(all_data)}")
        return all_data
        
    except Exception as e:
        logger.error(f"[J-Quants] API Error: {e}")
        raise

def sync_companies_to_db():
    """
    Fetch companies from API and sync to local database (Upsert).
    """
    db: Session = SessionLocal()
    try:
        companies_data = fetch_all_listed_companies()
        
        count = 0
        updated_count = 0
        
        for item in companies_data:
             ticker = item.get("Code")
             name = item.get("CoName")
             sector_17 = item.get("S17Nm")
             sector_33 = item.get("S33Nm")
             market = item.get("MktNm")
             
             if not ticker:
                 continue
                 
             code_4digit = ticker[:-1] if len(ticker) == 5 and ticker.endswith("0") else ticker
             
             existing = db.query(Company).filter(Company.ticker == ticker).first()
             
             if existing:
                 existing.name = name
                 existing.code_4digit = code_4digit
                 existing.sector_17 = sector_17
                 existing.sector_33 = sector_33
                 existing.market = market
                 existing.updated_at = datetime.utcnow()
                 updated_count += 1
             else:
                 new_company = Company(
                     ticker=ticker,
                     code_4digit=code_4digit,
                     name=name,
                     sector_17=sector_17,
                     sector_33=sector_33,
                     market=market,
                     last_sync_at=datetime.utcnow(),
                     updated_at=datetime.utcnow()
                 )
                 db.add(new_company)
                 count += 1
        
        db.commit()
        logger.info(f"[J-Quants] Sync Complete. Added: {count}, Updated: {updated_count}")
        return {"added": count, "updated": updated_count}
        
    except Exception as e:
        db.rollback()
        logger.error(f"[J-Quants] Sync Failed: {e}")
        raise
    finally:
        db.close()

def fetch_earnings_calendar():
    """
    Fetch earnings announcement dates from J-Quants API v2 (/equities/earnings-calendar).
    """
    if not API_KEY:
        logger.error("JQUANTS_API_KEY is not set.")
        raise ValueError("JQUANTS_API_KEY is missing")

    url = "https://api.jquants.com/v2/equities/earnings-calendar"
    headers = {"x-api-key": API_KEY}
    params = {}
    
    all_data = []
    
    try:
        print("[J-Quants] Fetching earnings calendar...")
        while True:
            res = requests.get(url, params=params, headers=headers)
            res.raise_for_status()
            
            d = res.json()
            data_chunk = d.get("data", [])
            all_data.extend(data_chunk)
            
            pagination_key = d.get("pagination_key")
            if pagination_key:
                params["pagination_key"] = pagination_key
                time.sleep(1)
                print(f"[J-Quants] Fetching next page... (Total so far: {len(all_data)})")
            else:
                break
                
        print(f"[J-Quants] Total earnings records fetched: {len(all_data)}")
        return all_data
        
    except Exception as e:
        print(f"[J-Quants] Earnings Calendar API Error: {e}")
        raise

def sync_earnings_to_db():
    """
    Fetch earnings calendar and update Company table with next_earnings_date.
    """
    db: Session = SessionLocal()
    try:
        earnings_data = fetch_earnings_calendar()
        
        updated_count = 0
        now = datetime.utcnow()
        
        for item in earnings_data:
            code = item.get("Code")
            announcement_date_str = item.get("Date")
            
            if not code or not announcement_date_str:
                continue
            
            try:
                announcement_date = date.fromisoformat(announcement_date_str)
            except ValueError:
                continue
            
            company = db.query(Company).filter(Company.ticker == code).first()
            if company:
                company.next_earnings_date = announcement_date
                company.earnings_updated_at = now
                updated_count += 1
        
        db.commit()
        print(f"[J-Quants] Earnings Sync Complete. Updated: {updated_count} companies")
        return {"updated": updated_count}
        
    except Exception as e:
        db.rollback()
        print(f"[J-Quants] Earnings Sync Failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    load_dotenv()
    API_KEY = os.getenv("JQUANTS_API_KEY")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--sync-earnings":
        sync_earnings_to_db()
    else:
        sync_companies_to_db()
