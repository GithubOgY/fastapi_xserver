"""
EDINET タクソノミ定義ファイル

XBRLタグ名と日本語概念名のマッピングを管理します。
EDINETのタクソノミは年度ごとに更新されるため、
このファイルを更新することで新しいタグに対応できます。

主な辞書:
- FALLBACK_MAPPING: XBRLタグ名 → 日本語ラベル（1:1マッピング）
- CONCEPT_GROUPS: 日本語概念 → XBRLタグ名リスト（複数のタグを1つの概念に統合）
- RATIO_ELEMENTS: 比率/パーセンテージを表す要素
- PER_SHARE_ELEMENTS: 1株当たりデータを表す要素
- COUNT_ELEMENTS: 数量を表す要素
- SALARY_ELEMENTS: 給与を表す要素

参考:
- EDINET タクソノミ仕様書: https://disclosure.edinet-fsa.go.jp/
- 2019年以降の従業員関連タグが大幅に改訂されています
"""

# ============================================================
# XBRL TAG → 日本語ラベル マッピング（1:1）
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
    
    # ========== 役員情報 (Officer Information) ==========
    "NameOfficer": "役員氏名",
    "TitleOfficer": "役職名",
    "BirthDateOfficer": "生年月日",
    "TermOfOfficeOfficer": "任期",
    "NumberOfSharesHeldOfficer": "所有株式数（役員）",
    "BriefPersonalHistoryOfficer": "略歴",
}


# ============================================================
# CONCEPT GROUPING - 複数のXBRLタグを1つの概念に統合
# Priority order: IFRS elements first, then JGAAP
# ============================================================

CONCEPT_GROUPS = {
    # ========== 損益計算書 ==========
    # Revenue - IFRS has "OperatingRevenues", JGAAP has "NetSales"
    "売上高": [
        "OperatingRevenuesIFRS",  # IFRS priority
        "OperatingRevenuesIFRSSummaryOfBusinessResults",
        "Revenues",
        "RevenuesIFRS",
        "NetSales", 
        "NetSalesSummaryOfBusinessResults",
        "Revenue",
        "SalesRevenues",
    ],
    # Operating Income
    "営業利益": [
        "OperatingIncomeIFRS",
        "OperatingIncomeIFRSSummaryOfBusinessResults",
        "OperatingProfitLossIFRS",
        "OperatingIncome", 
        "OperatingIncomeSummaryOfBusinessResults",
        "OperatingProfitLoss",
    ],
    # Ordinary Income (unique to Japan GAAP)
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
    
    # ========== 貸借対照表 ==========
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
    
    # ========== キャッシュ・フロー ==========
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
    
    # ========== 1株当たり指標 ==========
    # EPS
    "EPS": [
        "BasicEarningsLossPerShareIFRS",
        "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
        "BasicEarningsPerShare", 
        "BasicEarningsLossPerShare", 
        "BasicEarningsLossPerShareSummaryOfBusinessResults",
    ],
    
    # ========== 財務指標 ==========
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
    
    # ========== その他 ==========
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
        "MerchandiseAndFinishedGoods",
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
    
    # ============================================
    # 従業員関連 (2019年以降のタクソノミ)
    # ============================================
    # 従業員数 (連結/単独)
    "従業員数": [
        "NumberOfEmployees",
        "NumberOfEmployeesIFRS",
        "NumberOfEmployeesSummaryOfBusinessResults",
        # 単独従業員数
        "NumberOfEmployeesInformationAboutReportingCompanyInformationAboutEmployees",
    ],
    # 平均年齢 (2019年以降のタグ)
    "平均年齢": [
        "AverageAgeYearsInformationAboutReportingCompanyInformationAboutEmployees",
        "AverageAgeYearsOfEmployeesOfSubmittingCompanyInformationAboutEmployees",
        "AverageAgeOfEmployees",
        "AverageAgeInformationAboutEmployees",
    ],
    # 平均勤続年数 (2019年以降のタグ)
    "平均勤続年数": [
        "AverageLengthOfServiceYearsInformationAboutReportingCompanyInformationAboutEmployees",
        "AverageLengthOfServiceYearsOfEmployeesOfSubmittingCompanyInformationAboutEmployees",
        "AverageLengthOfServiceOfEmployees",
        "AverageLengthOfServiceInformationAboutEmployees",
    ],
    # 平均年収 (2019年以降のタグ)
    "平均年収": [
        "AverageAnnualSalaryInformationAboutReportingCompanyInformationAboutEmployees",
        "AverageAnnualSalaryYenOfEmployeesOfSubmittingCompanyInformationAboutEmployees",
        "AverageAnnualSalaryOfEmployees",
        "AverageAnnualSalaryInformationAboutEmployees",
    ],
    # 臨時従業員数
    "臨時従業員数": [
        "AverageNumberOfTemporaryWorkers",
        "AverageNumberOfTemporaryWorkersInformationAboutReportingCompanyInformationAboutEmployees",
    ],
    
    # ============================================
    # 役員情報 (jpcrp_cor 名前空間)
    # ============================================
    # 役員氏名
    "役員氏名": [
        "NameOfficer",
        "NameInformationAboutOfficers",
        "NameDirector",
    ],
    # 役職名（代表取締役社長、社外取締役など）
    "役職名": [
        "TitleOfficer",
        "TitleInformationAboutOfficers",
        "PositionOfficer",
    ],
    # 生年月日（YYYY-MM-DD形式）
    "生年月日": [
        "BirthDateOfficer",
        "DateOfBirthInformationAboutOfficers",
    ],
    # 任期（(注)1 のような参照文字あり）
    "任期": [
        "TermOfOfficeOfficer",
        "TermOfOfficeInformationAboutOfficers",
    ],
    # 所有株式数（千株か株か単位に注意）
    "所有株式数（役員）": [
        "NumberOfSharesHeldOfficer",
        "NumberOfSharesHeldInformationAboutOfficers",
    ],
    # 略歴（長文テキスト）
    "略歴": [
        "BriefPersonalHistoryOfficer",
        "BriefPersonalHistoryInformationAboutOfficers",
        "CareerSummaryOfficer",
    ],
}


# ============================================================
# 要素分類リスト
# ============================================================

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
    "AverageAgeOfEmployees", "AverageYearsOfServiceOfEmployees", "平均年齢", "平均勤続年数",
]

# Elements that represent salary/wage (should be formatted as 円, not 億円)
SALARY_ELEMENTS = [
    "AverageAnnualSalary", "AverageWages", "平均年収",
]


# ============================================================
# ヘルパー関数
# ============================================================

def get_japanese_label(xbrl_tag: str) -> str:
    """XBRLタグ名から日本語ラベルを取得"""
    return FALLBACK_MAPPING.get(xbrl_tag, xbrl_tag)


def get_xbrl_tags(concept: str) -> list:
    """日本語概念名からXBRLタグ名リストを取得"""
    return CONCEPT_GROUPS.get(concept, [])


def is_ratio_element(name: str) -> bool:
    """比率/パーセンテージ要素かどうか"""
    return any(r in name for r in RATIO_ELEMENTS)


def is_per_share_element(name: str) -> bool:
    """1株当たりデータ要素かどうか"""
    return any(p in name for p in PER_SHARE_ELEMENTS)


def is_count_element(name: str) -> bool:
    """数量要素かどうか"""
    return any(c in name for c in COUNT_ELEMENTS)


def is_salary_element(name: str) -> bool:
    """給与要素かどうか"""
    return any(s in name for s in SALARY_ELEMENTS)
