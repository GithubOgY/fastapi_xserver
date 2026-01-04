"""
Simple rate limiter for API endpoints
"""
from datetime import datetime, timedelta
from typing import Dict, Tuple
import logging

logger = logging.getLogger(__name__)

class SimpleRateLimiter:
    """
    シンプルなレート制限機能

    使用例:
        limiter = SimpleRateLimiter(max_requests=10, window_seconds=60)

        # リクエストが許可されるかチェック
        allowed, retry_after = limiter.check("user_ip_or_id")
        if not allowed:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded. Retry after {retry_after} seconds")
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        Args:
            max_requests: 時間窓内で許可される最大リクエスト数
            window_seconds: 時間窓の長さ（秒）
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, list] = {}  # {client_id: [timestamp1, timestamp2, ...]}

    def check(self, client_id: str) -> Tuple[bool, int]:
        """
        リクエストが許可されるかチェック

        Args:
            client_id: クライアントの識別子（IPアドレスやユーザーIDなど）

        Returns:
            (allowed, retry_after):
                - allowed: リクエストが許可される場合True
                - retry_after: 制限されている場合、何秒後に再試行できるか
        """
        now = datetime.utcnow()
        cutoff_time = now - timedelta(seconds=self.window_seconds)

        # 古いリクエスト記録を削除
        if client_id in self._requests:
            self._requests[client_id] = [
                req_time for req_time in self._requests[client_id]
                if req_time > cutoff_time
            ]
        else:
            self._requests[client_id] = []

        # リクエスト数をチェック
        request_count = len(self._requests[client_id])

        if request_count >= self.max_requests:
            # 最も古いリクエストから計算
            oldest_request = self._requests[client_id][0]
            retry_after = int((oldest_request + timedelta(seconds=self.window_seconds) - now).total_seconds()) + 1
            logger.warning(f"Rate limit exceeded for {client_id}: {request_count}/{self.max_requests}")
            return False, max(retry_after, 1)

        # リクエストを記録
        self._requests[client_id].append(now)
        return True, 0

    def reset(self, client_id: str):
        """特定のクライアントのレート制限をリセット"""
        if client_id in self._requests:
            del self._requests[client_id]

    def get_stats(self, client_id: str) -> Dict[str, int]:
        """クライアントの統計情報を取得"""
        now = datetime.utcnow()
        cutoff_time = now - timedelta(seconds=self.window_seconds)

        if client_id not in self._requests:
            return {
                "current_requests": 0,
                "max_requests": self.max_requests,
                "remaining": self.max_requests,
                "window_seconds": self.window_seconds
            }

        # 古いリクエストを除外
        current_requests = sum(1 for req_time in self._requests[client_id] if req_time > cutoff_time)

        return {
            "current_requests": current_requests,
            "max_requests": self.max_requests,
            "remaining": max(0, self.max_requests - current_requests),
            "window_seconds": self.window_seconds
        }


# グローバルなレート制限インスタンス
# パブリックAPIは1分間に10リクエスト
public_api_limiter = SimpleRateLimiter(max_requests=10, window_seconds=60)

# 認証済みユーザーは1分間に30リクエスト
authenticated_api_limiter = SimpleRateLimiter(max_requests=30, window_seconds=60)
