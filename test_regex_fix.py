"""
Test the fixed regex pattern for number extraction
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re

test_cases = [
    # Let's verify what the actual split should be by looking at the numbers:
    # 1,805,60513.84 → If ratio is last 5 chars "13.84", shares are "1,805,605"
    # 1,192,3319.14 → If ratio is last 5 chars "19.14", shares are "1,192,331" NO, that's 9.14!
    # So the pattern must be: last 4 or 5 chars = ratio, everything before = shares
    # BUT ratio must be < 100%
    #
    # Let me recalculate assuming ratio < 100:
    # 1,805,60513.84 → 13.84 (✓ < 100) → shares = 1,805,605
    # 1,192,3319.14 → 9.14 (✓ < 100) → shares = 1,192,331
    #   BUT if we take 19.14, that's also < 100...
    #   Wait, if shares are in thousands and ratio is %, the last digit of shares + ratio must make sense
    #   株式数(千株) means shares in 1000s
    #   If shares = 1,192,331 (thousand) = 1,192,331,000 shares, ratio = 9.14%
    #   Let me check: maybe the concatenation is: shares(without last comma group) + ratio
    #   1,192,331 → written as "1,192,331" but appears as "1,192,3319.14"
    #   So the split is at position: len - 5? No...
    #
    # INSIGHT: Shares in thousands: 1,805,605 thousands, ratio: 13.84%
    # These are concatenated WITHOUT the last part: 1,805,605 13.84 → 1,805,60513.84
    # So the split is: digits up to the SECOND-TO-LAST digit, then last 2 digits + decimal + 2 more

    ("港区赤坂一丁目８番１号1,805,60513.84", "1,805,605", "13.84"),
    ("刈谷市豊田町二丁目１番地1,192,3319.14", "1,192,331", "9.14"),
    ("中央区晴海一丁目８番12号811,6476.22", "811,647", "6.22"),
    ("大阪市中央区今橋三丁目５番12号633,2214.85", "633,221", "4.85"),
]

print("Testing APPROACH 1: r'([\\d,]+?)(\\d{1,2}\\.\\d{2})$'\n")

for test_str, expected_shares, expected_ratio in test_cases:
    match = re.search(r'([\d,]+?)(\d{1,2}\.\d{2})$', test_str)

    if match:
        shares_raw = match.group(1)
        ratio_raw = match.group(2)

        status = "✅" if shares_raw == expected_shares and ratio_raw == expected_ratio else "❌"

        print(f"{status} Test: {test_str[:50]}")
        print(f"   Expected: shares={expected_shares}, ratio={expected_ratio}")
        print(f"   Got:      shares={shares_raw}, ratio={ratio_raw}")
        print()
    else:
        print(f"❌ No match for: {test_str[:50]}\n")

print("\n" + "="*70)
print("Testing APPROACH 2: Extract last 4-5 chars, validate ratio < 100\n")

for test_str, expected_shares, expected_ratio in test_cases:
    # Extract all trailing digits and decimals
    match = re.search(r'([\d,]+)([\d.]+)$', test_str)

    if match:
        all_numbers = match.group(1) + match.group(2)
        # Try to split: last X.XX or XX.XX where value < 100

        # Find the decimal point
        if '.' in all_numbers:
            decimal_pos = all_numbers.rfind('.')
            # Get 2 digits after decimal
            after_decimal = all_numbers[decimal_pos+1:decimal_pos+3]

            # Try to get 1-2 digits before decimal such that ratio < 100
            for digits_before in [2, 1]:
                start_pos = decimal_pos - digits_before
                if start_pos >= 0:
                    ratio_candidate = all_numbers[start_pos:decimal_pos+3]
                    try:
                        ratio_value = float(ratio_candidate)
                        if 0 < ratio_value < 100:  # Valid ratio range
                            # Found the ratio
                            shares_raw = all_numbers[:start_pos].rstrip(',')
                            ratio_raw = ratio_candidate

                            status = "✅" if shares_raw == expected_shares and ratio_raw == expected_ratio else "❌"

                            print(f"{status} Test: {test_str[:50]}")
                            print(f"   Expected: shares={expected_shares}, ratio={expected_ratio}")
                            print(f"   Got:      shares={shares_raw}, ratio={ratio_raw}")
                            print()
                            break
                    except ValueError:
                        continue
    else:
        print(f"❌ No match for: {test_str[:50]}\n")
