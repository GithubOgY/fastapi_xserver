"""
EDINET API Integration Module

This module provides functions to fetch financial data from EDINET API
and parse XBRL data with Japanese account labels.
"""

import requests
import os
import tempfile
import zipfile
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)

# EDINET API Base URL
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

# Get API key from environment
# Note: EDINET_API_KEY should be set in .env file
EDINET_API_KEY = os.getenv("EDINET_API_KEY", "")

# Account mapping (English to Japanese)
# Using Unicode escapes to prevent encoding issues during file transfer
# 売上高, 営業利益, etc.
ACCOUNT_MAPPING = {
    # P/L
    "NetSales": "\u58b2\u4e0a\u9ad8",
    "OperatingIncome": "\u55b6\u696d\u5229\u76ca",
    "OrdinaryIncome": "\u7d4c\u5e38\u5229\u76ca",
    "NetIncome": "\u5f53\u671f\u7d14\u5229\u76ca",
    "NetIncomeAttributableToOwnersOfParent": "\u89aa\u4f1a\u793e\u682a\u4e3b\u306b\u5e30\u5c5e\u3059\u308b\u5f53\u671f\u7d14\u5229\u76ca",
    "GrossProfit": "\u58b2\u4e0a\u7dcf\u5229\u76ca",
    "SellingGeneralAndAdministrativeExpenses": "\u8ca9\u58f2\u8cbb\u53ca\u3073\u4e00\u822c\u7ba1\u7406\u8cbb",
    
    # B/S
    "TotalAssets": "\u7dcf\u8cc7\u7523",
    "TotalLiabilities": "\u8ca0\u50b5\u5408\u8a08",
    "NetAssets": "\u7d14\u8cc7\u7523",
    "CurrentAssets": "\u6d41\u52d5\u8cc7\u7523",
    "NonCurrentAssets": "\u56fa\u5b9a\u8cc7\u7523",
    
    # Cash Flow
    "CashFlowsFromOperatingActivities": "\u55b6\u696d\u6d3b\u52d5\u306b\u3088\u308b\u30ad\u30e3\u30c3\u30b7\u30e5\u30d5\u30ed\u30fc",
    "CashFlowsFromInvestingActivities": "\u6295\u8cc7\u6d3b\u52d5\u306b\u3088\u308b\u30ad\u30e3\u30c3\u30b7\u30e5\u30d5\u30ed\u30fc",
    "CashFlowsFromFinancingActivities": "\u8ca1\u52d9\u6d3b\u52d5\u306b\u3088\u308b\u30ad\u30e3\u30c3\u30b7\u30e5\u30d5\u30ed\u30fc",
    
    # Per Share
    "BasicEarningsPerShare": "1\u682a\u5f53\u305f\u308a\u5f53\u671f\u7d14\u5229\u76ca",
    "DividendPerShare": "1\u682a\u5f53\u305f\u308a\u914d\u5353\u91d1",
    "BookValuePerShare": "1\u682a\u5f53\u305f\u308a\u7d14\u8cc7\u7523",
}


def get_document_list(date: str = None) -> List[Dict]:
    """
    Get list of documents submitted on a specific date
    """
    if date is None:
        # Default to yesterday
        yesterday = datetime.now() - timedelta(days=1)
        date = yesterday.strftime("%Y-%m-%d")
    
    url = f"{EDINET_API_BASE}/documents.json"
    params = {"date": date, "type": 2, "Subscription-Key": EDINET_API_KEY}
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except Exception as e:
        logger.error(f"Failed to get document list: {e}")
        return []


def search_company_documents(company_code: str = None, company_name: str = None, 
                             doc_type: str = "120", days_back: int = 365) -> List[Dict]:
    """
    Search for company documents by code or name
    doc_type 120: Yuuka Shouken Houkokusho (Annual Report)
    """
    matching_docs = []
    
    # Search for the last N days
    # Note: This can be slow, in production we should optimize or cache
    for i in range(days_back):
        search_date = datetime.now() - timedelta(days=i)
        date_str = search_date.strftime("%Y-%m-%d")
        
        docs = get_document_list(date_str)
        
        for doc in docs:
            # Filter by document type
            if doc.get("docTypeCode") != doc_type:
                continue
            
            # Filter by company code or name
            if company_code and doc.get("secCode") == company_code:
                matching_docs.append(doc)
            elif company_name and company_name in doc.get("filerName", ""):
                matching_docs.append(doc)
        
        # Stop if we found documents
        if matching_docs:
            break
    
    return matching_docs


def download_xbrl_document(doc_id: str) -> Optional[str]:
    """
    Download XBRL document and extract to temp directory
    """
    url = f"{EDINET_API_BASE}/documents/{doc_id}"
    params = {"type": 1, "Subscription-Key": EDINET_API_KEY}
    
    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="edinet_")
        zip_path = os.path.join(temp_dir, f"{doc_id}.zip")
        
        # Save ZIP file
        with open(zip_path, "wb") as f:
            f.write(response.content)
        
        # Extract ZIP
        extract_dir = os.path.join(temp_dir, "xbrl")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        logger.info(f"Downloaded and extracted XBRL document to {extract_dir}")
        return extract_dir
    
    except Exception as e:
        logger.error(f"Failed to download XBRL document: {e}")
        return None


def parse_xbrl_financial_data(xbrl_dir: str) -> Dict[str, any]:
    """
    Parse XBRL financial data and extract key metrics
    """
    try:
        from edinet_xbrl.edinet_xbrl_parser import EdinetXbrlParser
        
        # Find XBRL file (usually ends with .xbrl)
        xbrl_file = None
        for root, dirs, files in os.walk(xbrl_dir):
            for file in files:
                if file.endswith(".xbrl") and "PublicDoc" in file:
                    xbrl_file = os.path.join(root, file)
                    break
            if xbrl_file:
                break
        
        if not xbrl_file:
            logger.error("XBRL file not found in directory")
            return {}
        
        # Parse XBRL
        parser = EdinetXbrlParser()
        data = parser.parse_file(xbrl_file)
        
        # Extract financial data using the key mapping
        financial_data = {}
        
        for eng_label, jp_label in ACCOUNT_MAPPING.items():
            try:
                # Try to get data for this account
                # Context ref "CurrentYearDuration" is typical for PL items
                # "CurrentYearInstant" is typical for BS items (needs check)
                
                # Try Duration (PL) first
                value = data.get_data_by_context_ref(
                    key=eng_label,
                    context_ref="CurrentYearDuration"
                )
                
                # If not found, try Instant (BS)
                if value is None:
                    value = data.get_data_by_context_ref(
                        key=eng_label,
                        context_ref="CurrentYearInstant"
                    )
                
                if value:
                    financial_data[jp_label] = value
            except:
                continue
        
        return financial_data
    
    except Exception as e:
        logger.error(f"Failed to parse XBRL: {e}")
        return {}


def get_company_financial_data(company_code: str) -> Dict[str, any]:
    """
    Get financial data for a company by its securities code
    Priority: Annual Report (120) > Quarterly Report (140)
    """
    # First try Annual Report (120) - Look back 365 days
    docs = search_company_documents(company_code=company_code, doc_type="120", days_back=365)
    
    # If not found, try Quarterly Report (140) - Look back 180 days
    if not docs:
        docs = search_company_documents(company_code=company_code, doc_type="140", days_back=180)
    
    if not docs:
        logger.warning(f"No documents found for company code {company_code}")
        return {}
    
    # Use the most recent document
    latest_doc = docs[0]
    doc_id = latest_doc.get("docID")
    doc_type = latest_doc.get("docDescription", "Unknown Document")
    logger.info(f"Using document: {doc_type} (ID: {doc_id})")
    
    # Download and parse XBRL
    xbrl_dir = download_xbrl_document(doc_id)
    if not xbrl_dir:
        return {}
    
    financial_data = parse_xbrl_financial_data(xbrl_dir)
    
    # Clean up temp directory
    try:
        import shutil
        shutil.rmtree(os.path.dirname(xbrl_dir))
    except:
        pass
    
    return financial_data
