"""
EDINET API のレート制限とキャッシング機能のテスト
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from utils.rate_limiter import SimpleRateLimiter
from utils.edinet_cache import EDINETCache
import time

print("=" * 70)
print("EDINET API機能テスト")
print("=" * 70)

# ===========================
# 1. レート制限のテスト
# ===========================
print("\n【1】レート制限テスト（10リクエスト/60秒）\n")

limiter = SimpleRateLimiter(max_requests=10, window_seconds=60)
client_id = "test_client_123"

# 10回リクエスト（すべて成功するはず）
for i in range(1, 11):
    allowed, retry_after = limiter.check(client_id)
    status = "✅ OK" if allowed else f"❌ BLOCKED (retry in {retry_after}s)"
    print(f"  Request {i:2d}: {status}")

# 11回目（制限されるはず）
print("\n  --- 制限を超えた場合 ---")
allowed, retry_after = limiter.check(client_id)
status = "✅ OK" if allowed else f"❌ BLOCKED (retry in {retry_after}s)"
print(f"  Request 11: {status}")

# 統計情報
stats = limiter.get_stats(client_id)
print(f"\n  統計情報: {stats}")

# ===========================
# 2. キャッシュのテスト
# ===========================
print("\n\n【2】キャッシュテスト（TTL=30分、最大100エントリ）\n")

cache = EDINETCache(ttl_minutes=30, max_size=100)

# データをキャッシュ
test_data = {
    "metadata": {
        "company_name": "トヨタ自動車",
        "securities_code": "7203",
        "period_end": "2025-03-31"
    },
    "normalized_data": {
        "売上高": 45000000000000,
        "営業利益": 5000000000000
    }
}

print("  データをキャッシュ: query=7203, doc_type=120")
cache.set("7203", test_data, "120")

# キャッシュから取得
print("  キャッシュから取得...")
cached_data = cache.get("7203", "120")
if cached_data:
    company_name = cached_data.get("metadata", {}).get("company_name")
    print(f"  ✅ キャッシュヒット: {company_name}")
else:
    print("  ❌ キャッシュミス")

# 存在しないキーを取得
print("\n  存在しないキーを取得...")
cached_data = cache.get("9999", "120")
if cached_data:
    print("  ❌ エラー: 存在しないはずのデータが返された")
else:
    print("  ✅ キャッシュミス（正常）")

# 統計情報
stats = cache.get_stats()
print(f"\n  キャッシュ統計: {stats}")

# ===========================
# 3. キャッシュサイズ制限のテスト
# ===========================
print("\n\n【3】キャッシュサイズ制限テスト（最大5エントリ）\n")

small_cache = EDINETCache(ttl_minutes=30, max_size=5)

# 6つのエントリを追加（最も古いものが削除されるはず）
for i in range(1, 7):
    small_cache.set(f"company_{i}", {"data": i}, "120")
    time.sleep(0.01)  # 順序を保証するため少し待機

print("  6つのエントリを追加しました")

# 最初のエントリは削除されているはず
first_entry = small_cache.get("company_1", "120")
if first_entry:
    print("  ❌ エラー: 最も古いエントリが削除されていない")
else:
    print("  ✅ 最も古いエントリが削除されました")

# 最後のエントリは存在するはず
last_entry = small_cache.get("company_6", "120")
if last_entry:
    print("  ✅ 最後のエントリは存在します")
else:
    print("  ❌ エラー: 最後のエントリが見つかりません")

stats = small_cache.get_stats()
print(f"\n  キャッシュ統計: {stats}")

print("\n" + "=" * 70)
print("テスト完了！")
print("=" * 70)
