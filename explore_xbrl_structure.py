"""
XBRL Structure Explorer
This script downloads an XBRL file and explores its structure,
especially the label files (*_lab.xml) for Japanese account names.
"""

import sys
import os

# Get the directory of this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)

from dotenv import load_dotenv
# Load from .env.example (where API key is stored)
load_dotenv(os.path.join(SCRIPT_DIR, ".env.example"))

import requests
import tempfile
import zipfile
from datetime import datetime, timedelta
from lxml import etree

EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
EDINET_API_KEY = os.getenv("EDINET_API_KEY", "")


def get_document_list(date: str):
    """Get document list for a specific date"""
    url = f"{EDINET_API_BASE}/documents.json"
    params = {"date": date, "type": 2, "Subscription-Key": EDINET_API_KEY}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("results", [])


def find_annual_report(days_back=30):
    """Find a corporate annual report (docTypeCode=120, jpcrp format) from recent days"""
    for i in range(days_back):
        search_date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        print(f"Searching {search_date}...")
        docs = get_document_list(search_date)
        
        for doc in docs:
            if doc.get("docTypeCode") == "120":  # Annual Report
                desc = doc.get("docDescription", "")
                # Skip investment trusts (投資信託) and REITs
                if "投資信託" in desc or "投資法人" in desc:
                    continue
                # Must be a corporate report with securities code
                if doc.get("secCode"):
                    return doc
    return None


def download_and_extract(doc_id: str) -> str:
    """Download XBRL zip and extract"""
    url = f"{EDINET_API_BASE}/documents/{doc_id}"
    params = {"type": 1, "Subscription-Key": EDINET_API_KEY}
    
    print(f"Downloading document {doc_id}...")
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    
    temp_dir = tempfile.mkdtemp(prefix="edinet_explore_")
    zip_path = os.path.join(temp_dir, f"{doc_id}.zip")
    
    with open(zip_path, "wb") as f:
        f.write(response.content)
    
    extract_dir = os.path.join(temp_dir, "xbrl")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    
    print(f"Extracted to: {extract_dir}")
    return extract_dir


def explore_structure(xbrl_dir: str):
    """Explore the XBRL directory structure"""
    print("\n" + "="*60)
    print("XBRL Directory Structure")
    print("="*60)
    
    all_files = []
    for root, dirs, files in os.walk(xbrl_dir):
        rel_root = os.path.relpath(root, xbrl_dir)
        for file in files:
            rel_path = os.path.join(rel_root, file) if rel_root != "." else file
            all_files.append(rel_path)
            print(f"  {rel_path}")
    
    return all_files


def parse_label_file(label_file_path: str):
    """Parse a label file and extract Japanese labels"""
    print("\n" + "="*60)
    print(f"Parsing Label File: {os.path.basename(label_file_path)}")
    print("="*60)
    
    tree = etree.parse(label_file_path)
    root = tree.getroot()
    
    # XBRL namespaces
    namespaces = {
        'link': 'http://www.xbrl.org/2003/linkbase',
        'xlink': 'http://www.w3.org/1999/xlink',
    }
    
    labels = {}
    
    # Find all label elements
    for label in root.findall('.//link:label', namespaces):
        role = label.get(f'{{{namespaces["xlink"]}}}role', '')
        label_text = label.text
        label_id = label.get(f'{{{namespaces["xlink"]}}}label', '')
        lang = label.get('{http://www.w3.org/XML/1998/namespace}lang', '')
        
        if label_text and lang == 'ja':
            labels[label_id] = {
                'text': label_text,
                'role': role,
                'lang': lang
            }
    
    # Print sample labels
    print(f"\nFound {len(labels)} Japanese labels")
    print("\nSample labels (first 20):")
    for i, (label_id, info) in enumerate(list(labels.items())[:20]):
        print(f"  {label_id}: {info['text']}")
    
    return labels


def parse_xbrl_file(xbrl_file_path: str):
    """Parse XBRL file and extract financial elements"""
    print("\n" + "="*60)
    print(f"Parsing XBRL File: {os.path.basename(xbrl_file_path)}")
    print("="*60)
    
    tree = etree.parse(xbrl_file_path)
    root = tree.getroot()
    
    # Collect unique element names and sample values
    elements = {}
    for elem in root.iter():
        tag = elem.tag
        if "}" in tag:
            ns, local_name = tag.split("}")
            ns = ns[1:]  # Remove leading {
        else:
            ns = ""
            local_name = tag
        
        if elem.text and elem.text.strip():
            if local_name not in elements:
                elements[local_name] = {
                    'namespace': ns,
                    'sample_value': elem.text.strip()[:50],
                    'count': 1
                }
            else:
                elements[local_name]['count'] += 1
    
    # Filter for interesting financial elements
    financial_keywords = [
        'Sales', 'Revenue', 'Income', 'Profit', 'Loss', 'Asset', 'Liability',
        'Equity', 'Cash', 'Operating', 'Expense', 'Capital', 'Dividend',
        'EarningsPerShare', 'ROE', 'ROA'
    ]
    
    print(f"\nTotal unique elements: {len(elements)}")
    print("\nFinancial Elements (matching keywords):")
    
    financial_elements = {}
    for name, info in elements.items():
        if any(kw.lower() in name.lower() for kw in financial_keywords):
            financial_elements[name] = info
            print(f"  {name}: {info['sample_value']} (count: {info['count']})")
    
    return elements, financial_elements


def main():
    print("XBRL Structure Explorer")
    print("="*60)
    
    if not EDINET_API_KEY:
        print("ERROR: EDINET_API_KEY not set")
        return
    
    # Find a recent annual report
    print("\n1. Finding a recent annual report...")
    doc = find_annual_report(days_back=30)
    
    if not doc:
        print("No annual report found in last 30 days")
        return
    
    print(f"\nFound: {doc.get('filerName')}")
    print(f"Document: {doc.get('docDescription')}")
    print(f"DocID: {doc.get('docID')}")
    print(f"SecCode: {doc.get('secCode')}")
    
    # Download and extract
    print("\n2. Downloading XBRL package...")
    xbrl_dir = download_and_extract(doc.get('docID'))
    
    # Explore structure
    print("\n3. Exploring directory structure...")
    files = explore_structure(xbrl_dir)
    
    # Find and parse label files
    print("\n4. Looking for label files...")
    label_files = [f for f in files if '_lab' in f.lower() and f.endswith('.xml')]
    print(f"Found {len(label_files)} label files:")
    for lf in label_files:
        print(f"  - {lf}")
    
    # Parse the first Japanese label file
    for lf in label_files:
        if '-ja' in lf.lower() or 'lab.xml' in lf.lower():
            label_path = os.path.join(xbrl_dir, lf)
            if os.path.exists(label_path):
                parse_label_file(label_path)
                break
    
    # Find and parse XBRL files
    print("\n5. Looking for XBRL data files...")
    xbrl_files = [f for f in files if f.endswith('.xbrl')]
    print(f"Found {len(xbrl_files)} XBRL files:")
    for xf in xbrl_files:
        print(f"  - {xf}")
    
    # Parse the main XBRL file (jpcrp preferred)
    for xf in xbrl_files:
        if 'jpcrp' in xf.lower():
            xbrl_path = os.path.join(xbrl_dir, xf)
            if os.path.exists(xbrl_path):
                parse_xbrl_file(xbrl_path)
                break
    
    # Keep the directory for manual inspection
    print("\n" + "="*60)
    print(f"XBRL files extracted to: {xbrl_dir}")
    print("You can manually inspect this directory.")
    print("="*60)


if __name__ == "__main__":
    main()
