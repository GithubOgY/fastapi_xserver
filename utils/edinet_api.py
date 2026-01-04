from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, Optional

SCHEMA_VERSION = "1.0"

_FINANCIAL_KEY_MAP = {
    "revenue": ("\u58f2\u4e0a\u9ad8",),
    "operating_income": ("\u55b6\u696d\u5229\u76ca",),
    "ordinary_income": ("\u7d4c\u5e38\u5229\u76ca",),
    "net_income": ("\u5f53\u671f\u7d14\u5229\u76ca",),
    "total_assets": ("\u7dcf\u8cc7\u7523",),
    "net_assets": ("\u7d14\u8cc7\u7523",),
    "cash_and_equivalents": (
        "\u73fe\u91d1\u540c\u7b49\u7269",
        "\u73fe\u91d1\u53ca\u3073\u73fe\u91d1\u540c\u7b49\u7269",
    ),
    "operating_cf": ("\u55b6\u696dCF",),
    "investing_cf": ("\u6295\u8cc7CF",),
    "financing_cf": ("\u8ca1\u52d9CF",),
    "free_cf": ("\u30d5\u30ea\u30fcCF",),
    "eps": ("EPS",),
    "dividend_per_share": (
        "\u914d\u5f53\u91d1",
        "\u0031\u682a\u5f53\u305f\u308a\u914d\u5f53\u91d1",
    ),
    "roe": ("ROE",),
    "equity_ratio": ("\u81ea\u5df1\u8cc7\u672c\u6bd4\u7387",),
    "per": ("PER",),
}

_TEXT_KEY_MAP = {
    "business_overview": ("\u4e8b\u696d\u306e\u5185\u5bb9",),
    "management_policy": ("\u7d4c\u55b6\u65b9\u91dd\u30fb\u7d4c\u55b6\u6226\u7565",),
    "management_analysis": ("\u7d4c\u55b6\u8005\u306b\u3088\u308b\u5206\u6790",),
    "financial_position_analysis": ("\u8ca1\u653f\u72b6\u614b\u306e\u5206\u6790",),
    "operating_results_analysis": ("\u7d4c\u55b6\u6210\u7e3e\u306e\u5206\u6790",),
    "cashflow_analysis": ("\u30ad\u30e3\u30c3\u30b7\u30e5\u30d5\u30ed\u30fc\u306e\u72b6\u6cc1",),
    "accounting_overview": ("\u7d4c\u7406\u306e\u72b6\u6cc1",),
    "significant_accounting_policies": ("\u91cd\u8981\u306a\u4f1a\u8a08\u65b9\u91dd",),
    "risks": ("\u4e8b\u696d\u7b49\u306e\u30ea\u30b9\u30af",),
    "issues": ("\u5bfe\u51e6\u3059\u3079\u304d\u8ab2\u984c",),
    "r_and_d": ("\u7814\u7a76\u958b\u767a\u6d3b\u52d5",),
    "capex": ("\u8a2d\u5099\u6295\u8cc7\u306e\u72b6\u6cc1",),
    "employees_info": ("\u5f93\u696d\u54e1\u306e\u72b6\u6cc1",),
    "governance": ("\u30b3\u30fc\u30dd\u30ec\u30fc\u30c8\u30ac\u30d0\u30ca\u30f3\u30b9",),
    "sustainability": ("\u30b5\u30b9\u30c6\u30ca\u30d3\u30ea\u30c6\u30a3",),
}

_RATIO_KEYS = {"roe", "equity_ratio"}


def normalize_edinet_query(query: str) -> str:
    if not query:
        return ""
    return query.strip().replace(".T", "").replace("\uff34", "")


def build_public_edinet_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    metadata = result.get("metadata", {}) or {}
    normalized = result.get("normalized_data", {}) or {}
    text_data = result.get("text_data", {}) or {}

    as_of = metadata.get("period_end") or date.today().isoformat()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "metadata": {
            "company_name": metadata.get("company_name"),
            "securities_code": metadata.get("securities_code"),
            "period_end": metadata.get("period_end"),
            "submit_date": metadata.get("submit_date"),
            "document_type": metadata.get("document_type"),
            "doc_id": metadata.get("doc_id"),
            "from_cache": metadata.get("from_cache"),
        },
        "financials": _extract_financials(normalized),
        "text": _extract_text(text_data),
        "website_url": result.get("website_url"),
    }

    return payload


def _extract_financials(normalized: Dict[str, Any]) -> Dict[str, Optional[float]]:
    output: Dict[str, Optional[float]] = {key: None for key in _FINANCIAL_KEY_MAP}

    for key, jp_keys in _FINANCIAL_KEY_MAP.items():
        raw_value = _pick_first(normalized, jp_keys)
        if key in _RATIO_KEYS:
            value = _ratio_to_decimal(raw_value)
        else:
            value = _to_number(raw_value)
        output[key] = value

    return output


def _extract_text(text_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    output: Dict[str, Optional[str]] = {key: None for key in _TEXT_KEY_MAP}

    for key, jp_keys in _TEXT_KEY_MAP.items():
        raw_value = _pick_first(text_data, jp_keys)
        if isinstance(raw_value, str):
            cleaned = raw_value.strip()
            output[key] = cleaned if cleaned else None
        else:
            output[key] = None

    return output


def _pick_first(data: Dict[str, Any], keys: Iterable[str]) -> Optional[Any]:
    for key in keys:
        if key in data:
            value = data.get(key)
            if value is not None and value != "":
                return value
    return None


def _to_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).replace(",", "")
        return float(text) if "." in text else float(int(text))
    except (TypeError, ValueError):
        return None


def _ratio_to_decimal(value: Any) -> Optional[float]:
    num = _to_number(value)
    if num is None:
        return None
    if abs(num) > 1:
        return num / 100.0
    return float(num)
