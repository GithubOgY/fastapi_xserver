# EDINET API 開発ガイド

このドキュメントは、EDINET APIを使用して日本企業の公式財務データを取得する方法を説明します。

## 📋 概要

**EDINET** (Electronic Disclosure for Investors' NETwork) は、金融庁が運営する電子開示システムです。
上場企業の有価証券報告書、四半期報告書などの公式開示資料をAPIで取得できます。

## 🔑 APIキーの取得

### 手順

1. **アカウント登録**
   - URL: https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1
   - ※ブラウザのポップアップブロックを解除する必要があります

2. **登録に必要な情報**
   - メールアドレス
   - パスワード
   - 電話番号（+81 Japan を選択、080-XXXXなら「80-XXXX...」と入力）

3. **多要素認証（MFA）を完了**

4. **APIキー発行**
   - 連絡先を登録後、32文字のAPIキーが発行されます
   - **必ず安全な場所に保存してください**

### 環境変数設定

```env
EDINET_API_KEY=your-32-character-api-key
```

## 🔧 実装方法

### 1. 必要なライブラリ

```python
import requests
import zipfile
import tempfile
from lxml import etree
```

### 2. API Base URL

```python
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
```

### 3. 書類一覧の取得

```python
def get_document_list(date: str, api_key: str):
    """
    特定日に提出された書類の一覧を取得
    
    Args:
        date: 日付 (YYYY-MM-DD形式)
        api_key: EDINET APIキー
    
    Returns:
        書類リスト (List[Dict])
    """
    url = f"{EDINET_API_BASE}/documents.json"
    params = {
        "date": date,
        "type": 2,  # type=2: メタデータ + XBRL
        "Subscription-Key": api_key
    }
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("results", [])
```

### 4. 書類タイプコード

| コード | 書類種類 |
|--------|---------|
| 120 | 有価証券報告書 |
| 130 | 訂正有価証券報告書 |
| 140 | 四半期報告書 |
| 150 | 訂正四半期報告書 |
| 160 | 半期報告書 |

### 5. 企業検索

```python
def search_company(company_name: str, doc_type: str = "120", days_back: int = 365):
    """
    企業名で書類を検索
    
    Args:
        company_name: 企業名（部分一致）
        doc_type: 書類タイプコード
        days_back: 何日前まで検索するか
    """
    for i in range(days_back):
        search_date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        docs = get_document_list(search_date, api_key)
        
        for doc in docs:
            if doc.get("docTypeCode") != doc_type:
                continue
            if company_name in doc.get("filerName", ""):
                return doc  # 最初に見つかった書類を返す
    
    return None
```

### 6. XBRLファイルのダウンロード

```python
def download_xbrl(doc_id: str, api_key: str):
    """
    XBRL書類をダウンロードして解凍
    
    Args:
        doc_id: 書類ID
        api_key: APIキー
    
    Returns:
        解凍先ディレクトリのパス
    """
    url = f"{EDINET_API_BASE}/documents/{doc_id}"
    params = {
        "type": 1,  # type=1: XBRL ZIPファイル
        "Subscription-Key": api_key
    }
    
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    
    # 一時ディレクトリに保存・解凍
    temp_dir = tempfile.mkdtemp(prefix="edinet_")
    zip_path = os.path.join(temp_dir, f"{doc_id}.zip")
    
    with open(zip_path, "wb") as f:
        f.write(response.content)
    
    extract_dir = os.path.join(temp_dir, "xbrl")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    
    return extract_dir
```

### 7. XBRLパース（lxml使用）

**重要**: `edinet-xbrl`ライブラリは最新のXBRL形式と互換性がないため、`lxml`を直接使用します。

```python
def parse_xbrl(xbrl_dir: str):
    """
    XBRLファイルをパースして財務データを抽出
    """
    # XBRLファイルを探す（jpcrpで始まるファイルを優先）
    xbrl_file = None
    for root, dirs, files in os.walk(xbrl_dir):
        for file in files:
            if file.endswith(".xbrl") and "jpcrp" in file:
                xbrl_file = os.path.join(root, file)
                break
    
    if not xbrl_file:
        return {}
    
    # lxmlでパース
    tree = etree.parse(xbrl_file)
    root = tree.getroot()
    
    # XBRL要素マッピング（IFRS形式）
    mapping = {
        "OperatingRevenuesIFRS": "売上高",
        "ProfitLossBeforeTaxIFRS": "税引前利益",
        "ProfitLossAttributableToOwnersOfParentIFRS": "親会社株主帰属利益",
        "TotalAssetsIFRS": "総資産",
        "TotalEquityIFRS": "純資産",
        "BasicEarningsLossPerShareIFRS": "1株当たり利益",
    }
    
    financial_data = {}
    
    for elem in root.iter():
        tag = elem.tag
        if "}" in tag:
            tag = tag.split("}")[1]
        
        for xbrl_key, jp_label in mapping.items():
            if xbrl_key in tag and elem.text and elem.text.strip():
                try:
                    value = int(elem.text.strip())
                    # 億円に変換
                    if value > 1000000000:
                        financial_data[jp_label] = f"{value / 100000000:,.0f}億円"
                    else:
                        financial_data[jp_label] = value
                except:
                    financial_data[jp_label] = elem.text.strip()
    
    return financial_data
```

## 📝 XBRL要素名一覧（主要項目）

### 損益計算書（IFRS）

| 要素名 | 日本語 |
|--------|--------|
| OperatingRevenuesIFRS | 売上高 |
| ProfitLossBeforeTaxIFRS | 税引前利益 |
| ProfitLossAttributableToOwnersOfParentIFRS | 親会社株主帰属利益 |
| ComprehensiveIncomeAttributableToOwnersOfParentIFRS | 包括利益 |
| BasicEarningsLossPerShareIFRS | 基本的1株当たり利益 |

### 貸借対照表（IFRS）

| 要素名 | 日本語 |
|--------|--------|
| TotalAssetsIFRS | 総資産 |
| TotalEquityIFRS | 純資産 |
| TotalLiabilitiesIFRS | 負債合計 |

### 日本基準（JGAAP）

| 要素名 | 日本語 |
|--------|--------|
| NetSales | 売上高 |
| OperatingIncome | 営業利益 |
| OrdinaryIncome | 経常利益 |
| NetIncome | 当期純利益 |
| TotalAssets | 総資産 |

## ⚠️ 注意点

1. **APIレート制限**: 大量リクエストは避ける
2. **書類サイズ**: 大企業のXBRLは数十MBになることがある
3. **日付指定**: 土日祝日は書類提出がない
4. **XBRL形式**: IFRS採用企業と日本基準企業で要素名が異なる
5. **一時ファイル**: ダウンロード後は必ずクリーンアップ

## 📚 参考リンク

- [EDINET 公式サイト](https://disclosure.edinet-fsa.go.jp/)
- [EDINET API仕様書 (Version 2)](https://disclosure.edinet-fsa.go.jp/EKW0EZ1001.html?lgKbn=2&dflg=0&iflg=0)
- [EDINETタクソノミ一覧](https://www.fsa.go.jp/search/20200731.html)

---

*作成日: 2025/12/27*
*最終更新: 2025/12/27*
