"""
EDINET API Test Script

Test the EDINET API integration and XBRL parsing
"""

import sys
sys.path.append(".")

from utils.edinet_api import (
    get_document_list,
    search_company_documents,
    get_company_financial_data
)

def test_document_list():
    """Test getting document list"""
    print("=== Testing Document List ===")
    docs = get_document_list()
    print(f"Found {len(docs)} documents")
    if docs:
        print(f"First document: {docs[0].get('filerName')} - {docs[0].get('docDescription')}")
    print()

def test_company_search():
    """Test searching for company documents"""
    print("=== Testing Company Search ===")
    # Test with Toyota (証券コード: 7203)
    company_code = "72030"  # EDINET uses 5-digit code
    docs = search_company_documents(company_code=company_code, days_back=180)
    print(f"Found {len(docs)} documents for company code {company_code}")
    for doc in docs[:3]:  # Show first 3
        print(f"  - {doc.get('filerName')}: {doc.get('docDescription')} ({doc.get('submitDateTime')})")
    print()

def test_financial_data():
    """Test getting financial data"""
    print("=== Testing Financial Data Extraction ===")
    company_code = "72030"  # Toyota
    print(f"Fetching financial data for company code {company_code}...")
    data = get_company_financial_data(company_code)
    
    if data:
        print("Financial Data (Japanese labels):")
        for label, value in data.items():
            print(f"  {label}: {value}")
    else:
        print("No financial data found")
    print()

if __name__ == "__main__":
    print("EDINET API Test\n" + "="*50 + "\n")
    
    # Run tests
    try:
        test_document_list()
    except Exception as e:
        print(f"Document list test failed: {e}\n")
    
    try:
        test_company_search()
    except Exception as e:
        print(f"Company search test failed: {e}\n")
    
    try:
        test_financial_data()
    except Exception as e:
        print(f"Financial data test failed: {e}\n")
    
    print("="*50)
    print("Test complete!")
