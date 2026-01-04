from __future__ import annotations

from datetime import date
import re
import unicodedata
from typing import Any, Dict, Iterable, Optional

SCHEMA_VERSION = "1.0"

_FINANCIAL_KEY_MAP = {
    "revenue": ("売上高",),
    "operating_income": ("営業利益",),
    "ordinary_income": ("経常利益",),
    "net_income": ("当期純利益",),
    "total_assets": ("総資産",),
    "net_assets": ("純資産",),
    "cash_and_equivalents": (
        "現金同等物",
        "現金及び現金同等物",
    ),
    "operating_cf": ("営業CF",),
    "investing_cf": ("投資CF",),
    "financing_cf": ("財務CF",),
    "free_cf": ("フリーCF",),
    "eps": ("EPS",),
    "dividend_per_share": (
        "配当金",
        "1株当たり配当金",
    ),
    "roe": ("ROE",),
    "equity_ratio": ("自己資本比率",),
    "per": ("PER",),
    # 従業員関連
    "employee_count": ("従業員数",),
    "average_age": ("平均年齢",),
    "average_tenure": ("平均勤続年数",),
    "average_salary": ("平均年収",),
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
_EMPLOYEE_METRICS = {"employee_count", "average_age", "average_tenure", "average_salary"}


def normalize_edinet_query(query: str) -> str:
    if not query:
        return ""
    return query.strip().replace(".T", "").replace("\uff34", "")


def normalize_securities_code(code: str) -> str:
    if not code:
        return ""
    cleaned = code.strip()
    if len(cleaned) == 5 and cleaned.endswith("0"):
        cleaned = cleaned[:-1]
    return cleaned


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


def build_essential_edinet_payload(
    latest_result: Dict[str, Any], 
    history: Iterable[Dict[str, Any]],
    metrics: Optional[Iterable[str]] = None
) -> Dict[str, Any]:
    """
    essentialビュー用のペイロードを構築
    
    Args:
        latest_result: 最新の財務データ
        history: 過去の財務データリスト
        metrics: 取得する指標のリスト（例: ["revenue", "operating_income", "roe"]）
                 Noneの場合はすべての主要指標を含む
    """
    metadata = latest_result.get("metadata", {}) or {}
    as_of = metadata.get("period_end") or date.today().isoformat()

    # デフォルト指標
    if metrics is None:
        metrics = ["revenue", "operating_income", "net_income", "operating_cf", "roe", "equity_ratio"]
    
    # 指標ごとの推移データを構築
    trends = _build_metric_trends(history, metrics)
    
    # ヒストリーがない場合はlatestから取得
    if not trends:
        latest_norm = latest_result.get("normalized_data", {}) or {}
        latest_raw = latest_result.get("raw_data", {}) or {}
        latest_text = latest_result.get("text_data", {}) or {}
        metrics_list = list(metrics)
        employee_fallback = None
        if any(metric in _EMPLOYEE_METRICS for metric in metrics_list):
            employee_fallback = _extract_employee_metrics_from_text(latest_text)
        trends = []
        trend_entry = {"period_end": metadata.get("period_end")}
        for metric in metrics_list:
            if metric in _FINANCIAL_KEY_MAP:
                raw_value = _pick_first(latest_norm, _FINANCIAL_KEY_MAP[metric])
                if raw_value is None:
                    raw_value = _pick_first(latest_raw, _FINANCIAL_KEY_MAP[metric])
                if raw_value is None and employee_fallback:
                    raw_value = employee_fallback.get(metric)
                if metric in _RATIO_KEYS:
                    trend_entry[metric] = _ratio_to_decimal(raw_value)
                else:
                    trend_entry[metric] = _to_number(raw_value)
        trends = [trend_entry]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "metadata": {
            "company_name": metadata.get("company_name"),
            "securities_code": normalize_securities_code(metadata.get("securities_code")),
            "period_end": metadata.get("period_end"),
            "submit_date": metadata.get("submit_date"),
            "document_type": metadata.get("document_type"),
            "doc_id": metadata.get("doc_id"),
            "from_cache": metadata.get("from_cache"),
        },
        "essential": {
            "metrics": list(metrics),
            "trends": trends,
        },
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


def _extract_employee_metrics_from_text(text_data: Dict[str, Any]) -> Dict[str, Optional[float]]:
    text = _get_employee_text(text_data)
    if not text or not isinstance(text, str):
        return {}

    normalized = unicodedata.normalize("NFKC", text)
    metrics: Dict[str, Optional[float]] = {}

    count_match = re.search(r"従業員数[^0-9]{0,10}([0-9][0-9,]*)", normalized)
    if count_match:
        metrics["employee_count"] = _to_number(count_match.group(1))

    age_match = re.search(r"平均年齢[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)", normalized)
    if age_match:
        metrics["average_age"] = _to_number(age_match.group(1))

    tenure_match = re.search(r"平均勤続年数[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)", normalized)
    if tenure_match:
        metrics["average_tenure"] = _to_number(tenure_match.group(1))

    salary_match = re.search(
        r"(平均年間給与|平均年収|平均給与)[^0-9]{0,10}([0-9][0-9,]*(?:\.[0-9]+)?)\s*(円|千円|万円|百万円|億円)?",
        normalized,
    )
    if salary_match:
        value = _to_number(salary_match.group(2))
        metrics["average_salary"] = _apply_unit_multiplier(value, salary_match.group(3))

    return metrics


def _get_employee_text(text_data: Dict[str, Any]) -> str:
    if not text_data:
        return ""
    for key, value in text_data.items():
        if "従業員" in key and isinstance(value, str):
            return value
    return ""


def _apply_unit_multiplier(value: Optional[float], unit: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    return value


def _build_metric_trends(
    history: Iterable[Dict[str, Any]], 
    metrics: Iterable[str]
) -> list[Dict[str, Any]]:
    """
    複数の指標の推移データを構築
    
    Args:
        history: 財務データの履歴リスト
        metrics: 取得する指標のリスト（例: ["revenue", "operating_income", "roe"]）
    
    Returns:
        [{"period_end": "2023-03-31", "revenue": 123456, "operating_income": 12345, ...}, ...]
    """
    trend: list[Dict[str, Any]] = []
    metrics_list = list(metrics)
    
    for item in history:
        meta = item.get("metadata", {}) or {}
        period_end = meta.get("period_end")
        normalized = item.get("normalized_data", {}) or {}
        raw_data = item.get("raw_data", {}) or {}
        text_data = item.get("text_data", {}) or {}
        employee_fallback = None
        if any(metric in _EMPLOYEE_METRICS for metric in metrics_list):
            employee_fallback = _extract_employee_metrics_from_text(text_data)
        
        entry = {"period_end": period_end}
        
        for metric in metrics_list:
            if metric in _FINANCIAL_KEY_MAP:
                raw_value = _pick_first(normalized, _FINANCIAL_KEY_MAP[metric])
                if raw_value is None:
                    raw_value = _pick_first(raw_data, _FINANCIAL_KEY_MAP[metric])
                if raw_value is None and employee_fallback:
                    raw_value = employee_fallback.get(metric)
                if metric in _RATIO_KEYS:
                    entry[metric] = _ratio_to_decimal(raw_value)
                else:
                    entry[metric] = _to_number(raw_value)
        
        trend.append(entry)
    
    return trend


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
