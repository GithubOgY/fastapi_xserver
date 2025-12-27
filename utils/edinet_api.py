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
EDINET_API_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"

# 勘定科目の英語→日本語マッピング
ACCOUNT_MAPPING = {
    # 損益計算書（P/L）
    "NetSales": "売上高",
    "OperatingIncome": "営業利益",
    "OrdinaryIncome": "経常利益",
    "NetIncome": "当期純利益",
    "NetIncomeAttributableToOwnersOfParent": "親会社株主に帰属する当期純利益",
    "GrossProfit": "売上総利益",
    "SellingGeneralAndAdministrativeExpenses": "販売費及び一般管理費",
    
    # 貸借対照表（B/S）
    "TotalAssets": "総資産",
    "TotalLiabilities": "負債合計",
    "NetAssets": "純資産",
    "CurrentAssets": "流動資産",
    "NonCurrentAssets": "固定資産",
    
    # キャッシュフロー
    "CashFlowsFromOperatingActivities": "営業活動によるキャッシュフロー",
    "CashFlowsFromInvestingActivities": "投資活動によるキャッシュフロー",
    "CashFlowsFromFinancingActivities": "財務活動によるキャッシュフロー",
    
    # その他
    "BasicEarningsPerShare": "1株当たり当期純利益",
    "DividendPerShare": "1株当たり配当金",
    "BookValuePerShare": "1株当たり純資産",
}


def get_document_list(date: str = None) -&gt; List[Dict]:
    """
    Get list of documents submitted on a specific date
    
    Args:
        date: Date in YYYY-MM-DD format (default: yesterday)
    
    Returns:
        List of document metadata
    """
    if date is None:
        # Default to yesterday
        yesterday = datetime.now() - timedelta(days=1)
        date = yesterday.strftime("%Y-%m-%d")
    
    url = f"{EDINET_API_BASE}/documents.json"
    params = {"date": date, "type": 2}  # type=2: metadata + XBRL
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except Exception as e:
        logger.error(f"Failed to get document list: {e}")
        return []


def search_company_documents(company_code: str = None, company_name: str = None, 
                             doc_type: str = "120", days_back: int = 365) -&gt; List[Dict]:
    """
    Search for company documents by code or name
    
    Args:
        company_code: Securities code (e.g., "7203" for Toyota)
        company_name: Company name (e.g., "トヨタ")
        doc_type: Document type code (120=有価証券報告書, 130=四半期報告書)
        days_back: Number of days to search back
    
    Returns:
        List of matching documents
    """
    matching_docs = []
    
    # Search for the last N days
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


def download_xbrl_document(doc_id: str) -&gt; Optional[str]:
    """
    Download XBRL document and extract to temp directory
    
    Args:
        doc_id: Document ID from EDINET
    
    Returns:
        Path to extracted XBRL directory, or None if failed
    """
    url = f"{EDINET_API_BASE}/documents/{doc_id}"
    params = {"type": 1}  # type=1: Get XBRL ZIP file
    
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


def parse_xbrl_financial_data(xbrl_dir: str) -&gt; Dict[str, any]:
    """
    Parse XBRL financial data and extract key metrics
    
    Args:
        xbrl_dir: Path to extracted XBRL directory
    
    Returns:
        Dictionary of financial data with Japanese labels
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
        
        # Extract financial data with Japanese labels
        financial_data = {}
        
        for eng_label, jp_label in ACCOUNT_MAPPING.items():
            try:
                # Try to get data for this account
                value = data.get_data_by_context_ref(
                    key=eng_label,
                    context_ref="CurrentYearDuration"  # Current fiscal year
                )
                if value:
                    financial_data[jp_label] = value
            except:
                continue
        
        return financial_data
    
    except Exception as e:
        logger.error(f"Failed to parse XBRL: {e}")
        return {}


def get_company_financial_data(company_code: str) -&gt; Dict[str, any]:
    """
    Get financial data for a company by its securities code
    
    Args:
        company_code: Securities code (e.g., "7203")
    
    Returns:
        Dictionary of financial data
    """
    # Search for recent documents
    docs = search_company_documents(company_code=company_code, days_back=180)
    
    if not docs:
        logger.warning(f"No documents found for company code {company_code}")
        return {}
    
    # Use the most recent document
    latest_doc = docs[0]
    doc_id = latest_doc.get("docID")
    
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
