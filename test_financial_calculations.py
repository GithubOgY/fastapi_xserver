"""
財務指標計算のテストスクリプト

このスクリプトは修正した財務指標計算ロジックが正しく動作することを検証します。
"""

from utils.financial_analysis import (
    calculate_profitability_metrics,
    calculate_efficiency_metrics,
    calculate_growth_rates
)

def test_roe_period_average():
    """ROEの期間平均計算をテスト"""
    print("\n=== ROE 期間平均計算テスト ===")

    # テストケース1: 期間平均を使用
    current = {"当期純利益": 1000, "純資産": 12000}
    previous = {"当期純利益": 800, "純資産": 10000}

    result = calculate_profitability_metrics(current, previous)

    # 期待値: 1000 / ((12000 + 10000) / 2) = 1000 / 11000 = 9.09%
    print(f"当期純利益: {current['当期純利益']}")
    print(f"当期純資産: {current['純資産']}")
    print(f"前期純資産: {previous['純資産']}")
    print(f"平均純資産: {(current['純資産'] + previous['純資産']) / 2}")
    print(f"ROE (期間平均): {result.get('ROE')}% (期待値: 9.09%)")
    print(f"計算方法: {result.get('ROE_計算方法')}")

    # テストケース2: 前期データなし（期末時点使用）
    result2 = calculate_profitability_metrics(current, None)

    # 期待値: 1000 / 12000 = 8.33%
    print(f"\nROE (期末時点): {result2.get('ROE')}% (期待値: 8.33%)")
    print(f"計算方法: {result2.get('ROE_計算方法')}")


def test_growth_rate_edge_cases():
    """成長率のエッジケースをテスト"""
    print("\n\n=== 成長率エッジケーステスト ===")

    # ケース1: 黒字転換
    print("\n【ケース1: 黒字転換】")
    current = {"営業利益": 500}
    previous = {"営業利益": -200}
    result = calculate_growth_rates(current, previous)
    print(f"前期: {previous['営業利益']}, 当期: {current['営業利益']}")
    print(f"成長率: {result.get('営業利益_成長率')}")
    print(f"備考: {result.get('営業利益_成長率_備考')}")

    # ケース2: 赤字転落
    print("\n【ケース2: 赤字転落】")
    current = {"営業利益": -300}
    previous = {"営業利益": 200}
    result = calculate_growth_rates(current, previous)
    print(f"前期: {previous['営業利益']}, 当期: {current['営業利益']}")
    print(f"成長率: {result.get('営業利益_成長率')}")
    print(f"備考: {result.get('営業利益_成長率_備考')}")

    # ケース3: 両期とも赤字
    print("\n【ケース3: 両期とも赤字】")
    current = {"営業利益": -150}
    previous = {"営業利益": -200}
    result = calculate_growth_rates(current, previous)
    print(f"前期: {previous['営業利益']}, 当期: {current['営業利益']}")
    print(f"成長率: {result.get('営業利益_成長率')}%")
    print(f"備考: {result.get('営業利益_成長率_備考')}")
    print(f"解釈: 赤字幅が縮小（改善）")

    # ケース4: 通常の成長
    print("\n【ケース4: 通常の成長】")
    current = {"売上高": 15000}
    previous = {"売上高": 12000}
    result = calculate_growth_rates(current, previous)
    print(f"前期: {previous['売上高']}, 当期: {current['売上高']}")
    print(f"成長率: {result.get('売上高_成長率')}% (期待値: 25.0%)")

    # ケース5: 前期ゼロ
    print("\n【ケース5: 前期ゼロ】")
    current = {"営業利益": 100}
    previous = {"営業利益": 0}
    result = calculate_growth_rates(current, previous)
    print(f"前期: {previous['営業利益']}, 当期: {current['営業利益']}")
    print(f"成長率: {result.get('営業利益_成長率')}")
    print(f"備考: {result.get('営業利益_成長率_備考')}")


def test_asset_turnover_period_average():
    """総資産回転率の期間平均計算をテスト"""
    print("\n\n=== 総資産回転率 期間平均計算テスト ===")

    current = {"売上高": 50000, "総資産": 30000}
    previous = {"売上高": 45000, "総資産": 28000}

    result = calculate_efficiency_metrics(current, previous)

    # 期待値: 50000 / ((30000 + 28000) / 2) = 50000 / 29000 = 1.72
    print(f"売上高: {current['売上高']}")
    print(f"当期総資産: {current['総資産']}")
    print(f"前期総資産: {previous['総資産']}")
    print(f"平均総資産: {(current['総資産'] + previous['総資産']) / 2}")
    print(f"総資産回転率 (期間平均): {result.get('総資産回転率')} (期待値: 1.72)")
    print(f"計算方法: {result.get('総資産回転率_計算方法')}")


def test_realistic_company_data():
    """実際の企業データに近いケースをテスト"""
    print("\n\n=== 実データに近いテストケース（トヨタ自動車を想定）===")

    # トヨタ自動車の概算データ（単位: 億円）
    current = {
        "売上高": 375000,
        "営業利益": 30000,
        "経常利益": 35000,
        "当期純利益": 25000,
        "総資産": 700000,
        "純資産": 280000,
    }

    previous = {
        "売上高": 360000,
        "営業利益": 28000,
        "経常利益": 32000,
        "当期純利益": 23000,
        "総資産": 680000,
        "純資産": 270000,
    }

    print("\n【収益性指標】")
    profitability = calculate_profitability_metrics(current, previous)
    print(f"営業利益率: {profitability.get('営業利益率')}%")
    print(f"経常利益率: {profitability.get('経常利益率')}%")
    print(f"純利益率: {profitability.get('純利益率')}%")
    print(f"ROE: {profitability.get('ROE')}% ({profitability.get('ROE_計算方法')})")
    print(f"ROA: {profitability.get('ROA')}% ({profitability.get('ROA_計算方法')})")

    print("\n【効率性指標】")
    efficiency = calculate_efficiency_metrics(current, previous)
    print(f"総資産回転率: {efficiency.get('総資産回転率')} ({efficiency.get('総資産回転率_計算方法')})")

    print("\n【成長率】")
    growth = calculate_growth_rates(current, previous)
    print(f"売上高成長率: {growth.get('売上高_成長率')}%")
    print(f"営業利益成長率: {growth.get('営業利益_成長率')}%")
    print(f"当期純利益成長率: {growth.get('当期純利益_成長率')}%")


if __name__ == "__main__":
    print("=" * 60)
    print("財務指標計算ロジック 検証テスト")
    print("=" * 60)

    test_roe_period_average()
    test_growth_rate_edge_cases()
    test_asset_turnover_period_average()
    test_realistic_company_data()

    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)
