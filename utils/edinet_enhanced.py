"""
EDINET Enhanced API - Hybrid Label Mapping System

This module provides enhanced XBRL parsing with:
1. Dynamic label file parsing for Japanese account names
2. Fallback dictionary for common elements
3. Comprehensive financial data extraction
"""

import os
import requests
import zipfile
import tempfile
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from lxml import etree

logger = logging.getLogger(__name__)

# EDINET API Base URL
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

# ============================================================
# COMPREHENSIVE FALLBACK MAPPING
# Covers IFRS, Japanese GAAP, and common variations
# ============================================================

FALLBACK_MAPPING = {
    # ========== Profit & Loss ==========
    # Revenue/Sales
    "NetSales": "売上高",
    "NetSalesSummaryOfBusinessResults": "売上高",
    "Revenue": "売上高",
    "OperatingRevenue": "営業収益",
    "OperatingRevenuesIFRS": "売上高(IFRS)",
    "RevenueFromContractsWithCustomers": "顧客との契約から生じる収益",
    
    # Gross Profit
    "GrossProfit": "売上総利益",
    "GrossProfitSummaryOfBusinessResults": "売上総利益",
    
    # Operating Income
    "OperatingIncome": "営業利益",
    "OperatingIncomeSummaryOfBusinessResults": "営業利益",
    "OperatingProfitLoss": "営業損益",
    
    # Ordinary Income (Japan GAAP specific)
    "OrdinaryIncome": "経常利益",
    "OrdinaryIncomeLoss": "経常損益",
    "OrdinaryIncomeLossSummaryOfBusinessResults": "経常利益",
    
    # Profit Before Tax
    "IncomeBeforeIncomeTaxes": "税引前当期純利益",
    "ProfitLossBeforeTaxIFRS": "税引前利益(IFRS)",
    "ProfitLossBeforeTax": "税引前利益",
    
    # Net Income
    "NetIncome": "当期純利益",
    "NetIncomeLoss": "当期純損益",
    "NetIncomeLossSummaryOfBusinessResults": "当期純利益",
    "ProfitLoss": "当期純利益",
    "ProfitLossAttributableToOwnersOfParent": "親会社株主に帰属する当期純利益",
    "ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults": "親会社株主に帰属する当期純利益",
    "ProfitLossAttributableToOwnersOfParentIFRS": "親会社株主帰属利益(IFRS)",
    
    # ========== Balance Sheet ==========
    # Assets
    "TotalAssets": "総資産",
    "TotalAssetsSummaryOfBusinessResults": "総資産",
    "TotalAssetsIFRS": "総資産(IFRS)",
    "Assets": "資産合計",
    "CurrentAssets": "流動資産",
    "NoncurrentAssets": "固定資産",
    "CashAndDeposits": "現金及び預金",
    "CashAndCashEquivalents": "現金及び現金同等物",
    "CashAndCashEquivalentsSummaryOfBusinessResults": "現金及び現金同等物",
    
    # Liabilities
    "TotalLiabilities": "負債合計",
    "TotalLiabilitiesIFRS": "負債合計(IFRS)",
    "CurrentLiabilities": "流動負債",
    "NoncurrentLiabilities": "固定負債",
    
    # Equity
    "NetAssets": "純資産",
    "NetAssetsSummaryOfBusinessResults": "純資産",
    "TotalEquity": "株主資本合計",
    "TotalEquityIFRS": "純資産(IFRS)",
    "ShareholdersEquity": "株主資本",
    "CapitalStock": "資本金",
    "CapitalStockSummaryOfBusinessResults": "資本金",
    "CapitalSurplus": "資本剰余金",
    "RetainedEarnings": "利益剰余金",
    
    # ========== Per Share Data ==========
    "BasicEarningsPerShare": "1株当たり当期純利益",
    "BasicEarningsLossPerShare": "1株当たり当期純損益",
    "BasicEarningsLossPerShareSummaryOfBusinessResults": "1株当たり当期純利益",
    "BasicEarningsLossPerShareIFRS": "1株当たり利益(IFRS)",
    "DilutedEarningsPerShare": "潜在株式調整後1株当たり当期純利益",
    "DilutedEarningsPerShareSummaryOfBusinessResults": "潜在株式調整後1株当たり当期純利益",
    "NetAssetsPerShare": "1株当たり純資産",
    "NetAssetsPerShareSummaryOfBusinessResults": "1株当たり純資産",
    "DividendPerShare": "1株当たり配当金",
    "DividendPerShareDividendsOfSurplus": "1株当たり配当金",
    "DividendPaidPerShareSummaryOfBusinessResults": "1株当たり配当金",
    
    # ========== Cash Flow Statement ==========
    "NetCashProvidedByUsedInOperatingActivities": "営業活動によるキャッシュ・フロー",
    "NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults": "営業活動によるキャッシュ・フロー",
    "CashFlowsFromOperatingActivities": "営業活動によるキャッシュ・フロー",
    
    "NetCashProvidedByUsedInInvestingActivities": "投資活動によるキャッシュ・フロー",
    "NetCashProvidedByUsedInInvestmentActivities": "投資活動によるキャッシュ・フロー",
    "NetCashProvidedByUsedInInvestingActivitiesSummaryOfBusinessResults": "投資活動によるキャッシュ・フロー",
    "CashFlowsFromInvestingActivities": "投資活動によるキャッシュ・フロー",
    
    "NetCashProvidedByUsedInFinancingActivities": "財務活動によるキャッシュ・フロー",
    "NetCashProvidedByUsedInFinancingActivitiesSummaryOfBusinessResults": "財務活動によるキャッシュ・フロー",
    "CashFlowsFromFinancingActivities": "財務活動によるキャッシュ・フロー",
    
    # ========== Key Ratios ==========
    "RateOfReturnOnEquity": "自己資本利益率(ROE)",
    "RateOfReturnOnEquitySummaryOfBusinessResults": "自己資本利益率(ROE)",
    "ReturnOnEquity": "自己資本利益率(ROE)",
    
    "EquityToAssetRatio": "自己資本比率",
    "EquityToAssetRatioSummaryOfBusinessResults": "自己資本比率",
    
    "PriceEarningsRatio": "株価収益率(PER)",
    "PriceEarningsRatioSummaryOfBusinessResults": "株価収益率(PER)",
    
    # ========== Dividend ==========
    "TotalAmountOfDividends": "配当金総額",
    "TotalAmountOfDividendsDividendsOfSurplus": "配当金総額",
    "DividendsFromSurplus": "剰余金の配当",
    "PayoutRatio": "配当性向",
    
    # ========== Other Important Items ==========
    "NumberOfEmployees": "従業員数",
    "NumberOfEmployeesSummaryOfBusinessResults": "従業員数",
    "CapitalExpenditures": "設備投資額",
    "CapitalExpendituresOverviewOfCapitalExpendituresEtc": "設備投資額",
    "DepreciationAndAmortization": "減価償却費",
    "ResearchAndDevelopmentExpenses": "研究開発費",
}

# ============================================================
# CONCEPT GROUPING - Map variations to canonical concepts
# Priority order: IFRS elements first, then JGAAP
# ============================================================

CONCEPT_GROUPS = {
    # Revenue - IFRS has "OperatingRevenues", JGAAP has "NetSales"
    "売上高": [
        "OperatingRevenuesIFRS",  # IFRS priority
        "OperatingRevenuesIFRSSummaryOfBusinessResults",
        "RevenueIFRS",
        "NetSales", 
        "NetSalesSummaryOfBusinessResults",
        "Revenue", 
        "OperatingRevenue",
        "RevenueFromContractsWithCustomers",
        "OrdinaryRevenue",
        "OrdinaryRevenues",
        "OperatingRevenue1",
        "OperatingRevenue2",
    ],
    # Operating Income
    "営業利益": [
        "OperatingProfitIFRS",
        "OperatingProfitIFRSSummaryOfBusinessResults",
        "OperatingIncome", 
        "OperatingIncomeSummaryOfBusinessResults",
        "OperatingProfitLoss",
    ],
    # Ordinary Income (Japan GAAP specific - IFRS doesn't have this)
    "経常利益": [
        "OrdinaryIncome", 
        "OrdinaryIncomeLoss", 
        "OrdinaryIncomeLossSummaryOfBusinessResults",
    ],
    # Net Income
    "当期純利益": [
        "ProfitLossAttributableToOwnersOfParentIFRS",
        "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
        "ProfitLossAttributableToOwnersOfParent", 
        "ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults",
        "NetIncome", 
        "NetIncomeLoss",
        "NetIncomeLossSummaryOfBusinessResults",
        "ProfitLoss",
    ],
    # Total Assets
    "総資産": [
        "TotalAssetsIFRS",
        "TotalAssetsIFRSSummaryOfBusinessResults",
        "TotalAssets", 
        "TotalAssetsSummaryOfBusinessResults",
        "Assets",
    ],
    # Net Assets / Equity
    "純資産": [
        "EquityAttributableToOwnersOfParentIFRS",
        "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
        "TotalEquityIFRS",
        "NetAssets", 
        "NetAssetsSummaryOfBusinessResults",
        "TotalEquity",
    ],
    # Cash Flows - Operating
    "営業CF": [
        "CashFlowsFromUsedInOperatingActivitiesIFRS",
        "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults",
        "NetCashProvidedByUsedInOperatingActivities", 
        "NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults",
        "CashFlowsFromOperatingActivities",
    ],
    # Cash Flows - Investing
    "投資CF": [
        "CashFlowsFromUsedInInvestingActivitiesIFRS",
        "CashFlowsFromUsedInInvestingActivitiesIFRSSummaryOfBusinessResults",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestmentActivities",
        "NetCashProvidedByUsedInInvestingActivitiesSummaryOfBusinessResults",
        "CashFlowsFromInvestingActivities",
    ],
    # Cash Flows - Financing
    "財務CF": [
        "CashFlowsFromUsedInFinancingActivitiesIFRS",
        "CashFlowsFromUsedInFinancingActivitiesIFRSSummaryOfBusinessResults",
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesSummaryOfBusinessResults",
        "CashFlowsFromFinancingActivities",
    ],
    # EPS
    "EPS": [
        "BasicEarningsLossPerShareIFRS",
        "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
        "BasicEarningsPerShare", 
        "BasicEarningsLossPerShare", 
        "BasicEarningsLossPerShareSummaryOfBusinessResults",
    ],
    # ROE
    "ROE": [
        "RateOfReturnOnEquityIFRS",
        "RateOfReturnOnEquityIFRSSummaryOfBusinessResults",
        "RateOfReturnOnEquity", 
        "RateOfReturnOnEquitySummaryOfBusinessResults", 
        "ReturnOnEquity",
    ],
    # Equity Ratio
    "自己資本比率": [
        "RatioOfOwnersEquityToGrossAssetsIFRS",
        "RatioOfOwnersEquityToGrossAssetsIFRSSummaryOfBusinessResults",
        "EquityToAssetRatio", 
        "EquityToAssetRatioSummaryOfBusinessResults",
    ],
    # Dividend Per Share
    "配当金": [
        "DividendPaidPerShareSummaryOfBusinessResults",
        "DividendPerShare", 
        "DividendPerShareDividendsOfSurplus",
    ],
    # PER
    "PER": [
        "PriceEarningsRatioIFRS",
        "PriceEarningsRatioIFRSSummaryOfBusinessResults",
        "PriceEarningsRatio",
        "PriceEarningsRatioSummaryOfBusinessResults",
    ],
    # Cash and Equivalents
    "現金同等物": [
        "CashAndCashEquivalentsIFRS",
        "CashAndCashEquivalentsIFRSSummaryOfBusinessResults",
        "CashAndCashEquivalents",
        "CashAndCashEquivalentsSummaryOfBusinessResults",
        "CashAndDeposits",
    ],
    # Current Assets (Safety)
    "流動資産": [
        "CurrentAssetsIFRS",
        "CurrentAssetsIFRSSummaryOfBusinessResults",
        "CurrentAssets", 
        "CurrentAssetsSummaryOfBusinessResults",
    ],
    # Current Liabilities (Safety)
    "流動負債": [
        "CurrentLiabilitiesIFRS",
        "CurrentLiabilitiesIFRSSummaryOfBusinessResults",
        "CurrentLiabilities", 
        "CurrentLiabilitiesSummaryOfBusinessResults",
    ],
    # Inventories (Efficiency)
    "棚卸資産": [
        "InventoriesIFRS",
        "InventoriesIFRSSummaryOfBusinessResults",
        "Inventories", 
        "InventoriesSummaryOfBusinessResults",
        "MerchandiseAndFinishedGoods", # Breakdown sum might be needed but main tag usually exists
    ],
    # Receivables (Efficiency - Notes & Accounts Receivable)
    "受取手形及び売掛金": [
        "TradeAndOtherReceivablesIFRS",
        "TradeAndOtherReceivablesIFRSSummaryOfBusinessResults",
        "NotesAndAccountsReceivableTrade", 
        "NotesAndAccountsReceivableTradeSummaryOfBusinessResults",
    ],
    # ROA (Return on Assets)
    "ROA": [
        "RateOfReturnOnAssetsIFRS",
        "RateOfReturnOnAssetsIFRSSummaryOfBusinessResults",
        "RateOfReturnOnAssets",
        "RateOfReturnOnAssetsSummaryOfBusinessResults",
        "ReturnOnAssets",
    ],
}

# Elements that represent ratios/percentages (value is 0-1 scale)
RATIO_ELEMENTS = [
    "RateOfReturnOnEquity", "ROE", "ReturnOnEquity",
    "EquityToAssetRatio", "RatioOfOwnersEquityToGrossAssets",
    "自己資本比率", "自己資本利益率",
]

# Elements that represent per-share data (should not be formatted as 億円)
PER_SHARE_ELEMENTS = [
    "EarningsPerShare", "DividendPerShare", "NetAssetsPerShare",
    "EPS", "配当金", "1株",
]

# Elements that represent counts (should not have 円 suffix)
COUNT_ELEMENTS = [
    "NumberOfEmployees", "NumberOfShares", "従業員数",
]


def get_api_key() -> str:
    """Get EDINET API key from environment"""
    # Try .env.example first (for development), then .env
    from dotenv import load_dotenv
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    
    # Try .env.example first
    env_example = os.path.join(parent_dir, ".env.example")
    if os.path.exists(env_example):
        load_dotenv(env_example)
    
    # Then .env (overrides)
    env_file = os.path.join(parent_dir, ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True)
    
    return os.getenv("EDINET_API_KEY", "")


def parse_label_file(xbrl_dir: str) -> Dict[str, str]:
    """
    Parse the Japanese label file (*_lab.xml) to extract element -> Japanese label mapping
    
    Returns:
        Dict mapping element local names to Japanese labels
    """
    labels = {}
    
    # Find label file
    label_file = None
    for root, dirs, files in os.walk(xbrl_dir):
        for f in files:
            if f.endswith("_lab.xml") and not f.endswith("_lab-en.xml"):
                label_file = os.path.join(root, f)
                break
        if label_file:
            break
    
    if not label_file:
        logger.warning("No Japanese label file found")
        return labels
    
    try:
        tree = etree.parse(label_file)
        root = tree.getroot()
        
        namespaces = {
            'link': 'http://www.xbrl.org/2003/linkbase',
            'xlink': 'http://www.w3.org/1999/xlink',
        }
        
        # Parse labelArcs to get href -> label mapping
        # Then parse labels to get label text
        for label in root.findall('.//link:label', namespaces):
            lang = label.get('{http://www.w3.org/XML/1998/namespace}lang', '')
            if lang != 'ja':
                continue
            
            label_id = label.get(f'{{{namespaces["xlink"]}}}label', '')
            text = label.text
            
            if text and label_id:
                # Extract element name from label_id
                # Format: jpcrp030000-asr_E39920-000_ElementName_label
                parts = label_id.split('_')
                if len(parts) >= 2:
                    # Get element name (second to last part, before 'label')
                    element_name = parts[-2] if parts[-1].startswith('label') else parts[-1]
                    labels[element_name] = text
        
        logger.info(f"Parsed {len(labels)} Japanese labels from label file")
        
    except Exception as e:
        logger.error(f"Failed to parse label file: {e}")
    
    return labels


def get_japanese_label(element_name: str, label_cache: Dict[str, str] = None) -> str:
    """
    Get Japanese label for an XBRL element name using hybrid approach:
    1. Check label cache (from label file)
    2. Check fallback mapping
    3. Return element name as-is
    """
    # Step 1: Check label cache
    if label_cache and element_name in label_cache:
        return label_cache[element_name]
    
    # Step 2: Check fallback mapping
    if element_name in FALLBACK_MAPPING:
        return FALLBACK_MAPPING[element_name]
    
    # Step 3: Try partial match in fallback
    for key, value in FALLBACK_MAPPING.items():
        if key in element_name:
            return value
    
    # Step 4: Return original name
    return element_name


def normalize_to_concept(element_name: str) -> Optional[str]:
    """
    Normalize various element names to canonical concept names
    Uses strict matching for ratio-based concepts to prevent false positives
    """
    # Concepts that require strict matching (no partial matching)
    strict_concepts = {"自己資本比率", "ROE", "PER"}
    
    for concept, variants in CONCEPT_GROUPS.items():
        # First check exact match
        if element_name in variants:
            return concept
        
        # For non-strict concepts, allow partial matching
        if concept not in strict_concepts:
            for variant in variants:
                if variant in element_name:
                    return concept
    
    return None


def extract_financial_data(xbrl_dir: str) -> Dict[str, Any]:
    """
    Extract comprehensive financial data from XBRL files
    
    Returns:
        Dict with:
        - raw_data: All extracted values keyed by Japanese labels
        - normalized_data: Key metrics normalized to canonical concepts
        - metadata: Document info
    """
    result = {
        "raw_data": {},
        "normalized_data": {},
        "text_data": {},
        "metadata": {},
    }
    
    # Find XBRL file (prefer jpcrp)
    xbrl_file = None
    for root, dirs, files in os.walk(xbrl_dir):
        for f in files:
            if f.endswith(".xbrl"):
                if "jpcrp" in f.lower():
                    xbrl_file = os.path.join(root, f)
                    break
                elif xbrl_file is None:
                    xbrl_file = os.path.join(root, f)
        if xbrl_file and "jpcrp" in xbrl_file.lower():
            break
    
    if not xbrl_file:
        logger.error("No XBRL file found")
        return result
    
    logger.info(f"Parsing XBRL: {os.path.basename(xbrl_file)}")
    
    # Parse label file first
    label_cache = parse_label_file(xbrl_dir)
    
    # Parse XBRL
    try:
        tree = etree.parse(xbrl_file)
        root = tree.getroot()
        
        # Define namespaces
        namespaces = {
            'jpcrp_cor': 'http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2023-03-31/jpcrp_cor', # Approximate
            'xbrli': 'http://www.xbrl.org/2003/instance',
            'link': 'http://www.xbrl.org/2003/linkbase'
        }

        # Context Analysis: Identify Current Year Contexts to avoid reading Prior Year data
        valid_contexts = set()
        context_dates = {}
        target_ns = namespaces['xbrli']
        
        try:
            # Find all contexts
            # Note: ElementTree findall needs full namespaced path or *
            # Using wildcard for safety against prefix variations
            for context in root.findall(f".//{{{target_ns}}}context"):
                c_id = context.get("id")
                if not c_id: continue
                
                # specific check for CurrentYear/CurrentPeriod
                if "CurrentYear" in c_id or "CurrentPeriod" in c_id:
                    valid_contexts.add(c_id)
                
                # Extract date to find the latest one
                date_val = None
                
                # Check for instant
                instant = context.find(f".//{{{target_ns}}}period/{{{target_ns}}}instant")
                if instant is not None and instant.text:
                    date_val = instant.text
                else:
                    # Check for endDate
                    end_date = context.find(f".//{{{target_ns}}}period/{{{target_ns}}}endDate")
                    if end_date is not None and end_date.text:
                        date_val = end_date.text
                
                if date_val:
                    context_dates[c_id] = date_val

            # Determine latest date
            if context_dates:
                latest_date = max(context_dates.values())
                logger.info(f"Latest context date identified in XBRL: {latest_date}")
                
                # Add all contexts matching the latest date to valid_contexts
                for c_id, d_val in context_dates.items():
                    if d_val == latest_date:
                        valid_contexts.add(c_id)
            
            logger.info(f"Selected valid context IDs: {len(valid_contexts)}")
            
        except Exception as e:
            logger.warning(f"Context analysis failed, falling back to simple filtering: {e}")
        
        # Extract qualitative text data
        text_data = {}
        
        # Text block mapping (Canonical Name -> Possible Tag Fragments)
        # Comprehensive list of qualitative information from EDINET
        text_targets = {
            "事業の内容": ["DescriptionOfBusinessTextBlock", "OverviewOfBusinessTextBlock"],
            "経営方針・経営戦略": ["ManagementPolicyBusinessPolicyAndManagementStrategyTextBlock", "ManagementPolicyTextBlock"],
            "経営者による分析": ["ManagementAnalysisOfFinancialPosition", "ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock", "OverviewOfBusinessResultsTextBlock"],
            # New financial-focused sections
            "財政状態の分析": ["AnalysisOfFinancialPositionTextBlock", "FinancialPositionTextBlock", "OverviewOfFinancialPositionTextBlock"],
            "経営成績の分析": ["AnalysisOfOperatingResultsTextBlock", "OperatingResultsTextBlock", "OverviewOfOperatingResultsTextBlock"],
            "キャッシュフローの状況": ["AnalysisOfCashFlowsTextBlock", "CashFlowsTextBlock", "OverviewOfCashFlowsTextBlock", "CashFlowPositionTextBlock"],
            "経理の状況": ["AccountingPoliciesTextBlock", "SignificantAccountingPoliciesTextBlock", "BusinessAccountingStandardsTextBlock"],
            "重要な会計方針": ["SignificantAccountingPoliciesAndEstimatesTextBlock", "AccountingEstimatesTextBlock"],
            "対処すべき課題": ["IssuesToBeAddressedTextBlock"],
            "事業等のリスク": ["BusinessRisksTextBlock", "RiskManagementTextBlock", "RisksOfBusinessEtcTextBlock"],
            "研究開発活動": ["ResearchAndDevelopmentActivitiesTextBlock"],
            "設備投資の状況": ["OverviewOfCapitalExpendituresEtcTextBlock", "CapitalExpendituresTextBlock"],
            "従業員の状況": ["InformationAboutEmployeesTextBlock", "EmployeesTextBlock"],
            "コーポレートガバナンス": ["CorporateGovernanceTextBlock", "StatusOfCorporateGovernanceTextBlock"],
            "役員の状況": ["InformationAboutOfficersTextBlock", "DirectorsAndExecutiveOfficersTextBlock", "DirectorsTextBlock"],
            "サステナビリティ": ["SustainabilityInformationTextBlock", "SustainabilityTextBlock", "EnvironmentalConservationActivitiesTextBlock"],
            # 株主構成情報
            "大株主の状況": ["MajorShareholdersTextBlock", "StatusOfMajorShareholdersTextBlock", "InformationAboutMajorShareholdersTextBlock", "MajorShareholders"],
            "株式の状況": ["StockInformationTextBlock", "StatusOfSharesTextBlock", "ShareInformationTextBlock"],
            "所有者別状況": ["StateOfShareholdingByOwnershipTextBlock", "ShareholdingByOwnershipTextBlock", "OwnershipOfSharesTextBlock"],
        }
        
        # Try to find text blocks
        for concept, frags in text_targets.items():
            for elem in root.iter():
                tag = elem.tag
                if not isinstance(tag, str):
                    continue
                
                # Context Filtering for Text
                # Text blocks also have contextRefs. We should prefer CurrentYear.
                context_ref = elem.get("contextRef")
                if context_ref and valid_contexts:
                    if context_ref not in valid_contexts:
                        continue
                elif context_ref and ("Prior" in context_ref or "Previous" in context_ref):
                    continue

                # Check if tag matches any fragment
                if any(frag in tag for frag in frags):
                    # Found a potential text block
                    raw_html = elem.text
                    if raw_html:
                        cleaned = clean_text_block(raw_html)
                        if len(cleaned) > 20: # Lowered threshold to 20 chars
                            text_data[concept] = cleaned
                            break # Found the best match for this concept
        
        result["text_data"] = text_data
        
        # Extract company website URL
        website_url = None
        website_tags = ["URLOfCompanyWebsite", "WebsiteOfCompany", "CompanyWebsite", "InformationAboutOfficialWebsiteOfCompany"]
        for elem in root.iter():
            tag = elem.tag
            if not isinstance(tag, str):
                continue
            if any(wt in tag for wt in website_tags):
                if elem.text and elem.text.strip().startswith("http"):
                    website_url = elem.text.strip()
                    break
        
        result["website_url"] = website_url
        
        # Extract all elements with values (numeric)
        for elem in root.iter():
            tag = elem.tag
            if not isinstance(tag, str):
                continue
            if "}" in tag:
                ns, local_name = tag.split("}")
                local_name = local_name
            else:
                local_name = tag
            
            # Skip non-data elements
            if not elem.text or not elem.text.strip():
                continue

            # Context Filtering
            # Ensure we only read data from the Current Year / Latest Date
            context_ref = elem.get("contextRef")
            if context_ref:
                # If we successfully identified valid contexts, strict filter
                if valid_contexts:
                    if context_ref not in valid_contexts:
                        continue
                # Fallback: Filter out obvious Prior/Previous year tags if context anaylsis failed
                elif "Prior" in context_ref or "Previous" in context_ref:
                    continue
            
            text = elem.text.strip()
            
            # Get Japanese label
            jp_label = get_japanese_label(local_name, label_cache)
            
            # Try to parse as number
            try:
                if "." in text:
                    value = float(text)
                else:
                    value = int(text.replace(",", ""))
            except ValueError:
                value = text
            
            # Store in raw_data
            if jp_label not in result["raw_data"]:
                result["raw_data"][jp_label] = value
            
            # Normalize to canonical concept
            concept = normalize_to_concept(local_name)
            if concept and concept not in result["normalized_data"]:
                result["normalized_data"][concept] = value
        
        # Calculate derived metrics if missing
        norm = result["normalized_data"]
        
        # Bank Fallback: Operating Income <- Ordinary Income
        if "営業利益" not in norm and "経常利益" in norm:
             norm["営業利益"] = norm["経常利益"]
        
        # Calculate FCF (Operating CF + Investing CF)
        if "フリーCF" not in norm:
             op_cf = norm.get("営業CF")
             inv_cf = norm.get("投資CF")
             if isinstance(op_cf, (int, float)) and isinstance(inv_cf, (int, float)):
                 norm["フリーCF"] = op_cf + inv_cf
                 
        # Calculate Equity Ratio
        if "自己資本比率" not in norm:
             equity = norm.get("純資産")
             assets = norm.get("総資産")
             if isinstance(equity, (int, float)) and isinstance(assets, (int, float)) and assets != 0:
                 norm["自己資本比率"] = (equity / assets) * 100
                 
        # Calculate ROE
        if "ROE" not in norm:
             net_income = norm.get("当期純利益")
             equity = norm.get("純資産")
             if isinstance(net_income, (int, float)) and isinstance(equity, (int, float)) and equity != 0:
                 norm["ROE"] = (net_income / equity) * 100
                 
        # Calculate ROA
        if "ROA" not in norm:
             net_income = norm.get("当期純利益")
             assets = norm.get("総資産")
             if isinstance(net_income, (int, float)) and isinstance(assets, (int, float)) and assets != 0:
                 norm["ROA"] = (net_income / assets) * 100
        
        # ============================================================
        # 株主構成データの抽出
        # ============================================================
        shareholder_data = []
        
        # 大株主の状況テキストブロックから株主情報をパース
        major_shareholders_html = text_data.get("大株主の状況", "")
        if major_shareholders_html:
            shareholder_data = parse_shareholder_table(major_shareholders_html)
            logger.info(f"Extracted {len(shareholder_data)} major shareholders")
        
        result["shareholder_data"] = shareholder_data
                 
        # Format large numbers
        result["formatted_data"] = format_financial_data(result["raw_data"])
        
        logger.info(f"Extracted {len(result['raw_data'])} raw items, {len(result['normalized_data'])} normalized items")
        
    except Exception as e:
        logger.error(f"Failed to parse XBRL: {e}")
        import traceback
        traceback.print_exc()
    
    return result


def parse_shareholder_table(html_content: str) -> List[Dict[str, Any]]:
    """
    大株主の状況 HTMLテーブルから株主データを抽出
    
    Returns:
        List of dicts with:
        - name: 株主名
        - shares: 所有株式数（株）- 整数
        - ratio: 持株比率（%）- 0-100のfloat
        - notes: 備考（あれば）
    
    注意事項:
    - 持株比率: EDINETでは通常パーセント値で記載（例: 10.5 = 10.5%）
    - 所有株式数: 千株単位で記載される場合あり（ヘッダーを確認）
    """
    shareholders = []
    
    if not html_content:
        return shareholders
    
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Find all tables
        tables = soup.find_all("table")
        
        for table in tables:
            rows = table.find_all("tr")
            if not rows:
                continue
            
            # Find header row to identify column structure
            header_row = None
            header_cols = []
            
            for row in rows:
                ths = row.find_all("th")
                tds = row.find_all("td")
                
                # ヘッダー行の特定（株主名、持株数、比率などのキーワードを探す）
                cells = ths if ths else tds
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                
                # 株主名関連のキーワードを探す
                has_name_col = any(any(kw in t for kw in ["氏名", "名称", "株主", "所有者"]) for t in cell_texts)
                # 株式数関連のキーワードを探す
                has_shares_col = any(any(kw in t for kw in ["株式数", "持株数", "所有株式", "保有株数"]) for t in cell_texts)
                
                if has_name_col and has_shares_col:
                    header_row = row
                    header_cols = cell_texts
                    break
            
            if not header_row:
                continue
            
            # カラムインデックスを特定
            name_col_idx = -1
            shares_col_idx = -1
            ratio_col_idx = -1
            
            for i, header in enumerate(header_cols):
                header_lower = header.lower()
                if name_col_idx == -1 and any(kw in header for kw in ["氏名", "名称", "株主", "所有者"]):
                    name_col_idx = i
                elif shares_col_idx == -1 and any(kw in header for kw in ["株式数", "持株数", "所有株式", "保有株数"]):
                    shares_col_idx = i
                elif ratio_col_idx == -1 and any(kw in header for kw in ["割合", "比率", "持株比率", "議決権"]):
                    ratio_col_idx = i
            
            # 千株単位かどうか確認
            is_thousand_unit = "千株" in "".join(header_cols) or "（千株）" in "".join(header_cols)
            
            # データ行を処理
            header_passed = False
            for row in rows:
                if row == header_row:
                    header_passed = True
                    continue
                if not header_passed:
                    continue
                
                cells = row.find_all(["td", "th"])
                if len(cells) <= max(name_col_idx, shares_col_idx, ratio_col_idx):
                    continue
                
                try:
                    # 株主名を取得
                    name_text = cells[name_col_idx].get_text(strip=True) if name_col_idx >= 0 else ""
                    
                    # 空の行やヘッダー風の行をスキップ
                    if not name_text or name_text in ["計", "合計", "その他", "自己名義"]:
                        continue
                    if any(kw in name_text for kw in ["株主名", "氏名又は名称"]):
                        continue
                    
                    # 所有株式数を取得
                    shares_raw = cells[shares_col_idx].get_text(strip=True) if shares_col_idx >= 0 else "0"
                    shares = parse_share_number(shares_raw, is_thousand_unit)
                    
                    # 持株比率を取得
                    ratio_raw = cells[ratio_col_idx].get_text(strip=True) if ratio_col_idx >= 0 else "0"
                    ratio = parse_ratio_percentage(ratio_raw)
                    
                    # 有効なデータのみ追加
                    if name_text and (shares > 0 or ratio > 0):
                        shareholders.append({
                            "name": name_text,
                            "shares": shares,  # 株数（整数）
                            "ratio": ratio,    # パーセント値（0-100）
                        })
                        
                except (IndexError, ValueError) as e:
                    logger.debug(f"Skipping row due to parse error: {e}")
                    continue
            
            # 1つのテーブルから株主を取得できたら終了
            if shareholders:
                break
        
    except Exception as e:
        logger.error(f"Failed to parse shareholder table: {e}")
    
    return shareholders


def parse_share_number(raw_text: str, is_thousand_unit: bool = False) -> int:
    """
    株式数をパース（整数で返す）
    
    Args:
        raw_text: 生のテキスト（例: "1,234,567", "1234千株"）
        is_thousand_unit: 千株単位かどうか
    
    Returns:
        株式数（株単位の整数）
    """
    if not raw_text:
        return 0
    
    # 数値以外の文字を除去（カンマ、スペース、千株など）
    cleaned = raw_text.replace(",", "").replace("，", "").replace(" ", "")
    cleaned = cleaned.replace("千株", "").replace("株", "").replace("千", "")
    
    # 数値を抽出
    import re
    match = re.search(r'([\d.]+)', cleaned)
    if not match:
        return 0
    
    try:
        num = float(match.group(1))
        
        # 千株単位の場合は1000倍
        if is_thousand_unit:
            num = num * 1000
        
        return int(num)
    except ValueError:
        return 0


def parse_ratio_percentage(raw_text: str) -> float:
    """
    持株比率をパース（パーセント値として返す: 0-100）
    
    Args:
        raw_text: 生のテキスト（例: "10.5", "10.5%", "0.105"）
    
    Returns:
        パーセント値（0-100のfloat）
        例: 入力が "10.5" or "10.5%" → 返り値 10.5
            入力が "0.105"（小数形式）→ 返り値 10.5
    """
    if not raw_text:
        return 0.0
    
    # %記号とスペースを除去
    cleaned = raw_text.replace("%", "").replace("％", "").replace(" ", "")
    
    # 数値を抽出
    import re
    match = re.search(r'([\d.]+)', cleaned)
    if not match:
        return 0.0
    
    try:
        num = float(match.group(1))
        
        # 0-1の範囲（小数形式）の場合は100倍してパーセントに変換
        # 例: 0.105 → 10.5%
        # ただし、1未満かつ0.5未満の値は小数形式と判断
        # （50%以上の持株比率は単独で過半数なので稀）
        if 0 < num < 1:
            num = num * 100
        
        # 最大100%を超える場合はエラー（ありえない）
        if num > 100:
            logger.warning(f"Ratio {num}% exceeds 100%, capping at 100")
            num = 100.0
        
        return round(num, 2)
    except ValueError:
        return 0.0


def clean_text_block(html_content: str) -> str:
    """
    Clean HTML text block from XBRL to plain text
    Removes tags, normalizes whitespace, and merges fragmented lines for better readability.
    """
    if not html_content:
        return ""
        
    try:
        # Pre-process: replace br/p/div with explicit newlines
        # XBRL often nests nonNumeric tags which causes fragmentation.
        # We strip tags but insert newlines only for structural elements.
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Replace line breaks
        for br in soup.find_all(["br", "BR"]):
            br.replace_with("\n")
            
        # Treat block elements as paragraph breaks
        for block in soup.find_all(["p", "div", "P", "DIV", "tr", "TR"]):
            block.insert_after("\n")
            
        # Extract text without separator to avoid breaking words found in span/ix:nonNumeric
        text = soup.get_text(separator="")
        
        # Post-processing normalization
        import re
        
        # 1. Remove carriage returns and tabs
        text = text.replace("\r", "").replace("\t", "")
        
        # 2. Re-join split lines
        # Often EDINET text looks like: "This year sales \n 100 billion yen \n was recorded."
        # We want to merge lines unless the previous line ends with specific punctuation.
        
        # First, split into lines
        raw_lines = text.split('\n')
        cleaned_lines = []
        
        # List markers that should start a new line
        markers = ["(1)", "(2)", "(3)", "①", "②", "③", "・", "－", "1.", "2.", "3."]
        
        current_line_buffer = ""
        
        for line in raw_lines:
            stripped = line.strip()
            # Replace full-width space with half-width or remove if excessive
            stripped = stripped.replace("　", " ")
            
            if not stripped:
                continue
                
            # Decision: Should we merge this line with the previous buffer?
            # Yes if:
            # 1. Previous buffer doesn't end with typical sentence enders (。, ．, ：)
            # 2. Current line doesn't start with a list marker
            
            should_merge = False
            if current_line_buffer:
                # Check previous ending
                ends_sentence = current_line_buffer.strip().endswith(("。", "．", "：", "!", "?", "！", "？"))
                # Check current starting
                starts_marker = any(stripped.startswith(m) for m in markers)
                
                if not ends_sentence and not starts_marker:
                    should_merge = True
            
            if should_merge:
                current_line_buffer += stripped
            else:
                if current_line_buffer:
                    cleaned_lines.append(current_line_buffer)
                current_line_buffer = stripped
                
        # Append the last buffer
        if current_line_buffer:
            cleaned_lines.append(current_line_buffer)
            
        # Join with newlines
        formatted_text = "\n".join(cleaned_lines)
        
        # Final cleanup for parenthesis hacks sometimes seen in XBRL extraction
        # e.g. "（ \n 1.5% \n ）" -> "（1.5%）"
        # Since we already merged lines, this might be "（ 1.5% ）"
        formatted_text = re.sub(r'（\s*', '（', formatted_text)
        formatted_text = re.sub(r'\s*）', '）', formatted_text)
        
        return formatted_text
        
    except Exception as e:
        logger.warning(f"Failed to clean text block: {e}")
        # Fallback to simple strip
        tag_clean = re.compile('<.*?>')
        return re.sub(tag_clean, '', str(html_content)).strip()


def is_ratio_key(key: str) -> bool:
    """Check if key represents a ratio/percentage"""
    ratio_keywords = [
        "ROE", "ROA", "比率", "Ratio", "Rate", "Margin",
        "利益率", "自己資本", "配当性向", "Payout",
    ]
    return any(kw.lower() in key.lower() for kw in ratio_keywords)


def is_per_share_key(key: str) -> bool:
    """Check if key represents per-share data"""
    per_share_keywords = [
        "EPS", "1株", "PerShare", "配当金",
    ]
    return any(kw in key for kw in per_share_keywords)


def is_count_key(key: str) -> bool:
    """Check if key represents a count (not currency)"""
    count_keywords = [
        "従業員", "Employees", "株式数", "Shares", "人員",
    ]
    return any(kw in key for kw in count_keywords)


def format_financial_data(data: Dict[str, Any]) -> Dict[str, str]:
    """Format financial data for display with smart detection"""
    formatted = {}
    
    for key, value in data.items():
        # Skip non-numeric values
        if isinstance(value, str):
            formatted[key] = str(value)[:100]  # Truncate long text
            continue
        
        # Handle ratios (ROE, 自己資本比率, etc.)
        if is_ratio_key(key):
            if isinstance(value, (int, float)):
                # Sanity check: ratios shouldn't exceed 10000% normally
                # Changed from 2 (200%) to 100 (10000%) to accommodate extreme ROE etc.
                if abs(value) > 100:
                    # Likely misidentified - treat as currency or skip
                    logger.debug(f"Skipping abnormal ratio value for {key}: {value}")
                    formatted[key] = f"{value:,.2f} (異常値)"
                elif abs(value) <= 1:  # Value is in decimal form (e.g., 0.102 = 10.2%)
                    formatted[key] = f"{value * 100:.1f}%"
                else:  # Value is already in percentage form (e.g., 10.2)
                    formatted[key] = f"{value:.1f}%"
            else:
                formatted[key] = f"{value}%"
            continue
        
        # Handle per-share data
        if is_per_share_key(key):
            if isinstance(value, float):
                formatted[key] = f"{value:,.2f}円"
            else:
                formatted[key] = f"{value:,}円"
            continue
        
        # Handle count data (employees, shares, etc.)
        if is_count_key(key):
            if isinstance(value, int):
                if abs(value) >= 10000:
                    formatted[key] = f"{value / 10000:,.1f}万人"
                else:
                    formatted[key] = f"{value:,}人"
            else:
                formatted[key] = f"{value:,}"
            continue
        
        # Handle regular currency values
        if isinstance(value, int):
            if abs(value) >= 1000000000000:  # 1兆円以上
                formatted[key] = f"{value / 1000000000000:,.2f}兆円"
            elif abs(value) >= 100000000:  # 1億円以上
                formatted[key] = f"{value / 100000000:,.1f}億円"
            elif abs(value) >= 10000:  # 1万円以上
                formatted[key] = f"{value / 10000:,.1f}万円"
            else:
                formatted[key] = f"{value:,}"
        elif isinstance(value, float):
            if abs(value) >= 1000000000000:  # 1兆円以上
                formatted[key] = f"{value / 1000000000000:,.2f}兆円"
            elif abs(value) >= 100000000:  # 1億円以上
                formatted[key] = f"{value / 100000000:,.1f}億円"
            elif abs(value) >= 10000:  # 1万円以上
                formatted[key] = f"{value / 10000:,.1f}万円"
            elif abs(value) >= 1:
                formatted[key] = f"{value:,.2f}"
            else:
                formatted[key] = f"{value:.4f}"
        else:
            formatted[key] = str(value)
    
    return formatted


def download_xbrl_package(doc_id: str) -> Optional[str]:
    """Download and extract XBRL package"""
    api_key = get_api_key()
    if not api_key:
        logger.error("EDINET_API_KEY not set")
        return None
    
    url = f"{EDINET_API_BASE}/documents/{doc_id}"
    params = {"type": 1, "Subscription-Key": api_key}
    
    try:
        logger.info(f"Downloading document {doc_id}...")
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()
        
        temp_dir = tempfile.mkdtemp(prefix="edinet_")
        zip_path = os.path.join(temp_dir, f"{doc_id}.zip")
        
        with open(zip_path, "wb") as f:
            f.write(response.content)
        
        extract_dir = os.path.join(temp_dir, "xbrl")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        logger.info(f"Extracted to: {extract_dir}")
        return extract_dir
        
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None


def get_document_list(date: str = None) -> List[Dict]:
    """Get document list for a specific date"""
    api_key = get_api_key()
    if not api_key:
        return []
    
    if date is None:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"{EDINET_API_BASE}/documents.json"
    params = {"date": date, "type": 2, "Subscription-Key": api_key}
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("results", [])
    except Exception as e:
        logger.error(f"Failed to get document list: {e}")
        return []


def search_company_reports(
    company_code: str = None,
    company_name: str = None,
    doc_type: str = "120",
    days_back: int = 365
) -> List[Dict]:
    """
    Search for company reports using parallel processing to speed up date traversal
    """
    matching_docs = []
    
    # List of dates to search
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_back)]
    
    def process_date(date_str):
        docs = get_document_list(date_str)
        found = []
        if not docs:
            return found
            
        for doc in docs:
            if doc.get("docTypeCode") != doc_type:
                continue
            
            # Skip investment trusts
            desc = doc.get("docDescription", "")
            if "投資信託" in desc or "投資法人" in desc:
                continue
            
            # Match by code or name
            if company_code:
                sec_code = doc.get("secCode", "")
                if sec_code and sec_code.startswith(company_code):
                    found.append(doc)
            elif company_name:
                filer_name = doc.get("filerName", "")
                if company_name in filer_name:
                    found.append(doc)
        return found

    # Execute in parallel
    # Use 10 workers for list retrieval (lightweight)
    logger.info(f"Searching {days_back} days in parallel...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_date = {executor.submit(process_date, date): date for date in dates}
        
        for i, future in enumerate(as_completed(future_to_date)):
            try:
                results = future.result()
                if results:
                    matching_docs.extend(results)
            except Exception as e:
                # Log only on debug to avoid noise
                logger.debug(f"Error searching date: {e}")
            
            # Log progress periodically
            if days_back > 100 and i % 100 == 0 and i > 0:
                logger.debug(f"Progress: {i}/{days_back} days checked")

    # Return sorted by submit date (newest first)
    matching_docs.sort(key=lambda x: x.get("submitDateTime", ""), reverse=True)
    
    logger.info(f"Found {len(matching_docs)} documents")
    return matching_docs


def process_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single document: download, extract, and parse
    Uses database cache to avoid repeated API calls (cache expires after 7 days)
    """
    import json
    from datetime import datetime, timedelta
    
    doc_id = doc.get("docID")
    period_end = doc.get("periodEnd")
    sec_code = doc.get("secCode", "")[:4] if doc.get("secCode") else ""
    
    # Try to get from cache first
    try:
        from database import SessionLocal, EdinetCache
        db = SessionLocal()
        
        # Check cache (7 days expiry)
        cache_expiry = datetime.utcnow() - timedelta(days=7)
        cached = db.query(EdinetCache).filter(
            EdinetCache.doc_id == doc_id,
            EdinetCache.cached_at > cache_expiry
        ).first()
        
        if cached:
            result = json.loads(cached.data_json)
            
            # キャッシュに株主データがない場合は無効化して再取得
            if "shareholder_data" not in result:
                print(f"[CACHE STALE] {doc_id} - missing shareholder_data, re-fetching")
                db.query(EdinetCache).filter(EdinetCache.doc_id == doc_id).delete()
                db.commit()
                db.close()
                # キャッシュを削除したので、この後の処理で再取得される
            else:
                print(f"[CACHE HIT] {doc_id} - {doc.get('filerName')}")
                db.close()
                # Add cache flag to metadata
                if "metadata" in result:
                    result["metadata"]["from_cache"] = True
                return result
        
        db.close()
    except Exception as e:
        print(f"[CACHE ERROR] {e}")
    
    # Cache miss - download and process
    print(f"[CACHE MISS] Downloading: {doc.get('filerName')} - {doc.get('docDescription')} ({period_end})")
    
    # Download and extract
    xbrl_dir = download_xbrl_package(doc_id)
    if not xbrl_dir:
        return {}
    
    # Extract financial data
    result = extract_financial_data(xbrl_dir)
    
    # Log text_data extraction result for debugging
    text_data_keys = list(result.get("text_data", {}).keys())
    logger.info(f"EDINET text_data keys extracted for {doc_id}: {text_data_keys}")
    
    # Add metadata with cache flag
    result["metadata"] = {
        "company_name": doc.get("filerName"),
        "document_type": doc.get("docDescription"),
        "submit_date": doc.get("submitDateTime"),
        "period_end": period_end,
        "securities_code": doc.get("secCode"),
        "doc_id": doc_id,
        "from_cache": False,
    }
    
    # Cleanup temp files
    try:
        shutil.rmtree(os.path.dirname(xbrl_dir))
    except:
        pass
    
    # Save to cache
    try:
        db = SessionLocal()
        
        # Remove old cache for this doc_id if exists
        db.query(EdinetCache).filter(EdinetCache.doc_id == doc_id).delete()
        
        # Add new cache entry
        cache_entry = EdinetCache(
            company_code=sec_code,
            doc_id=doc_id,
            period_end=period_end,
            data_json=json.dumps(result, ensure_ascii=False, default=str),
            cached_at=datetime.utcnow()
        )
        db.add(cache_entry)
        db.commit()
        logger.info(f"Cached data for {doc_id}")
        db.close()
    except Exception as e:
        logger.warning(f"Cache save failed: {e}")
    
    return result


def get_financial_history(company_code: str, years: int = 5) -> List[Dict[str, Any]]:
    """
    Get financial history for a company (up to N years)
    Prioritizes Annual Reports (120) and ensures one entry per fiscal year.
    """
    # Search range: years * 365 days + buffer
    days_back = years * 366 + 100
    
    # Search for annual reports
    logger.info(f"Searching for {years} years of history for {company_code}...")
    try:
        docs = search_company_reports(company_code=company_code, doc_type="120", days_back=days_back)
        logger.info(f"search_company_reports returned {len(docs)} documents for {company_code}")
    except Exception as e:
        logger.error(f"Error in search_company_reports for {company_code}: {e}", exc_info=True)
        return []
    
    history = []
    processed_periods = set()
    
    # Sort docs by submitDateTime descending (newest first)
    # This ensures we process the latest correction/version for each period first
    docs.sort(key=lambda x: x.get("submitDateTime", ""), reverse=True)
    
    for doc in docs:
        period_end = doc.get("periodEnd")
        
        # Skip if we already have data for this fiscal period
        if period_end in processed_periods:
            continue
            
        # Process the document
        data = process_document(doc)
        if data and data.get("normalized_data"):
            history.append(data)
            processed_periods.add(period_end)
            
        # Stop if we have enough years
        if len(history) >= years:
            break
    
    # Sort history by period_end (oldest to newest) for charting
    history.sort(key=lambda x: x["metadata"].get("period_end", ""))
    
    return history


def get_company_financials(company_code: str) -> Dict[str, Any]:
    """
    Get comprehensive financial data for a company (latest available)
    
    Args:
        company_code: Securities code (4 digits)
    
    Returns:
        Dict with financial data, or empty dict if not found
    """
    # Search for annual report first
    docs = search_company_reports(company_code=company_code, doc_type="120", days_back=365)
    
    # Fall back to quarterly report
    if not docs:
        docs = search_company_reports(company_code=company_code, doc_type="140", days_back=180)
    
    if not docs:
        logger.warning(f"No reports found for {company_code}")
        return {}
    
    # Use the latest document
    return process_document(docs[0])


# ============================================================
# CLI Test
# ============================================================

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    code = sys.argv[1] if len(sys.argv) > 1 else "7203"  # Default: Toyota
    
    print(f"\n{'='*60}")
    print(f"Fetching financial data for securities code: {code}")
    print('='*60)
    
    result = get_company_financials(code)
    
    if result:
        print(f"\n--- Metadata ---")
        for k, v in result.get("metadata", {}).items():
            print(f"  {k}: {v}")
        
        # Format normalized_data separately for display
        normalized = result.get("normalized_data", {})
        formatted_normalized = format_financial_data(normalized)
        
        print(f"\n--- Normalized Key Metrics ({len(normalized)} items) ---")
        # Display in a logical order
        display_order = [
            "売上高", "営業利益", "経常利益", "当期純利益",
            "総資産", "純資産", "現金同等物",
            "営業CF", "投資CF", "財務CF",
            "EPS", "配当金", "ROE", "自己資本比率", "PER"
        ]
        for key in display_order:
            if key in formatted_normalized:
                print(f"  {key}: {formatted_normalized[key]}")
        
        # Show any remaining keys not in display_order
        for k, v in formatted_normalized.items():
            if k not in display_order:
                print(f"  {k}: {v}")
        
        print(f"\n--- Sample Raw Data (first 20 financial items) ---")
        count = 0
        for k, v in result.get("formatted_data", {}).items():
            # Skip metadata-like entries
            if any(skip in k.lower() for skip in ['identifier', 'instant', 'member', 'date', 'measure', 'textblock']):
                continue
            print(f"  {k}: {v}")
            count += 1
            if count >= 20:
                break
    else:
        print("No data found")

