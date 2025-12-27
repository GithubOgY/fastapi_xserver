"""
EDINET API Test Script - Fixed version
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
        doc = docs[0]
        print(f"First document: {doc.get('filerName')} - {doc.get('docDescription')}")
    print()

def test_company_search():
    """Test searching for company documents by NAME (more reliable)"""
    print("=== Testing Company Search ===")
    # Use company NAME instead of code for more reliable search
    company_name = "Toyota"  # Will match partial name in English version
    
    # First try Japanese name
    print(f"Searching for 'Toyota' in filer names...")
    docs = search_company_documents(company_name="Toyota", doc_type="120", days_back=365)
    
    if not docs:
        # Try with Japanese name
        docs = search_company_documents(company_name="\u30c8\u30e8\u30bf", doc_type="120", days_back=365)
    
    print(f"Found {len(docs)} documents")
    for doc in docs[:3]:  # Show first 3
        print(f"  - {doc.get('filerName')}: {doc.get('docDescription')}")
        print(f"    SecCode: {doc.get('secCode')}, DocID: {doc.get('docID')}")
    print()

def test_financial_data():
    """Test getting financial data by company name"""
    print("=== Testing Financial Data Extraction ===")
    
    # Use get_company_financial_data with name search
    print("Fetching financial data for Toyota...")
    
    # Search by name first to get the correct secCode
    docs = search_company_documents(company_name="\u30c8\u30e8\u30bf\u81ea\u52d5\u8eca", doc_type="120", days_back=365)
    
    if docs:
        doc = docs[0]
        print(f"Found: {doc.get('filerName')}")
        print(f"Document: {doc.get('docDescription')}")
        print(f"SecCode: {doc.get('secCode')}")
        
        # Now test get_company_financial_data
        data = get_company_financial_data(doc.get('secCode'))
        
        if data:
            print("Financial Data (Japanese labels):")
            for label, value in data.items():
                print(f"  {label}: {value}")
        else:
            print("No financial data extracted (may need edinet-xbrl library)")
    else:
        print("No documents found for Toyota")
    print()

if __name__ == "__main__":
    print("EDINET API Test (Fixed)\n" + "="*50 + "\n")
    
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
        import traceback
        traceback.print_exc()
        print(f"Financial data test failed: {e}\n")
    
    print("="*50)
    print("Test complete!")
