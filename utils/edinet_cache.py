"""
Simple in-memory cache for EDINET API responses
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

class EDINETCache:
    """
    EDINETレスポンスの簡易インメモリキャッシュ

    使用例:
        cache = EDINETCache(ttl_minutes=30)

        # キャッシュから取得
        data = cache.get("7203")
        if data is None:
            # EDINET APIを呼び出し
            data = fetch_from_edinet("7203")
            cache.set("7203", data)
    """

    def __init__(self, ttl_minutes: int = 30, max_size: int = 100):
        """
        Args:
            ttl_minutes: キャッシュの有効期限（分）
            max_size: 最大キャッシュエントリ数
        """
        self.ttl_minutes = ttl_minutes
        self.max_size = max_size
        self._cache: Dict[str, Dict[str, Any]] = {}  # {key: {"data": ..., "expires_at": ...}}

    def _generate_key(self, query: str, doc_type: str = "120") -> str:
        """クエリからキャッシュキーを生成"""
        key_string = f"{query}:{doc_type}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, query: str, doc_type: str = "120") -> Optional[Dict[str, Any]]:
        """
        キャッシュからデータを取得

        Args:
            query: 企業コードまたは企業名
            doc_type: 文書タイプ（デフォルト: "120"）

        Returns:
            キャッシュされたデータ、または None（期限切れまたは存在しない場合）
        """
        key = self._generate_key(query, doc_type)

        if key not in self._cache:
            return None

        entry = self._cache[key]
        expires_at = entry.get("expires_at")

        # 期限切れチェック
        if datetime.utcnow() > expires_at:
            logger.debug(f"Cache expired for key: {key}")
            del self._cache[key]
            return None

        logger.info(f"Cache hit for query: {query}, doc_type: {doc_type}")
        return entry.get("data")

    def set(self, query: str, data: Dict[str, Any], doc_type: str = "120"):
        """
        データをキャッシュに保存

        Args:
            query: 企業コードまたは企業名
            data: キャッシュするデータ
            doc_type: 文書タイプ（デフォルト: "120"）
        """
        # キャッシュサイズが上限に達したら、最も古いエントリを削除
        if len(self._cache) >= self.max_size:
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].get("expires_at")
            )
            logger.debug(f"Cache full, removing oldest entry: {oldest_key}")
            del self._cache[oldest_key]

        key = self._generate_key(query, doc_type)
        expires_at = datetime.utcnow() + timedelta(minutes=self.ttl_minutes)

        self._cache[key] = {
            "data": data,
            "expires_at": expires_at,
            "created_at": datetime.utcnow()
        }

        logger.info(f"Cached data for query: {query}, doc_type: {doc_type}, expires_at: {expires_at}")

    def clear(self):
        """すべてのキャッシュをクリア"""
        self._cache.clear()
        logger.info("Cache cleared")

    def remove(self, query: str, doc_type: str = "120"):
        """特定のエントリを削除"""
        key = self._generate_key(query, doc_type)
        if key in self._cache:
            del self._cache[key]
            logger.info(f"Removed cache for query: {query}, doc_type: {doc_type}")

    def get_stats(self) -> Dict[str, Any]:
        """キャッシュの統計情報を取得"""
        now = datetime.utcnow()
        active_entries = sum(
            1 for entry in self._cache.values()
            if entry.get("expires_at") > now
        )

        return {
            "total_entries": len(self._cache),
            "active_entries": active_entries,
            "expired_entries": len(self._cache) - active_entries,
            "max_size": self.max_size,
            "ttl_minutes": self.ttl_minutes
        }


# グローバルなキャッシュインスタンス
# EDINETデータは30分間キャッシュ
edinet_cache = EDINETCache(ttl_minutes=30, max_size=100)
