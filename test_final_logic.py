"""
Final logic: Work with original comma-preserved string
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re

test_cases = [
    ("1,805,60513.84", "1,805,605", "13.84"),
    ("1,192,3319.14", "1,192,331", "9.14"),
    ("811,6476.22", "811,647", "6.22"),
    ("633,2214.85", "633,221", "4.85"),
]

print("FINAL LOGIC: Work with comma-preserved string\n")
print("Pattern: shares (with commas) + ratio → concatenated at boundary\n")
print("Example: 1,805,605 + 13.84 → 1,805,60513.84 (shares end with '5', ratio starts with '1', merged as '51')\n")
print("="*70 + "\n")

for combined_str, expected_shares, expected_ratio in test_cases:
    # Find decimal point position
    decimal_pos = combined_str.find('.')

    if decimal_pos == -1:
        print(f"❌ No decimal found in: {combined_str}\n")
        continue

    # Extract 2 digits after decimal (ratio decimal part)
    ratio_decimal = combined_str[decimal_pos+1:decimal_pos+3]

    # Try 2-digit first, then 1-digit
    found_match = False
    for ratio_int_digits in [2, 1]:
        ratio_int_start = decimal_pos - ratio_int_digits
        if ratio_int_start < 0:
            continue

        # Extract ratio
        ratio_candidate = combined_str[ratio_int_start:decimal_pos+3]

        try:
            ratio_float = float(ratio_candidate)
            if not (0 < ratio_float < 100):
                continue

            # Everything before the ratio integer part is shares + first digit of ratio
            # For 1-digit ratio: shares end  is at ratio_int_start - 1, but last char is shared
            # For 2-digit ratio: shares end is at ratio_int_start

            # NO SHARING! Just literal concatenation
            # Example: 1,192,331 + 9.14 → 1,192,3319.14 (just put them together)
            # Example: 1,805,605 + 13.84 → 1,805,60513.84 (just put them together)
            shares_candidate = combined_str[:ratio_int_start]
            print(f"  DEBUG {ratio_int_digits}-digit: ratio_int_start={ratio_int_start}, shares_candidate='{shares_candidate}', ratio={ratio_candidate}")

            # Validate: shares should have comma pattern X,XXX,XXX or similar
            # Remove commas and check it's all digits
            shares_no_comma = shares_candidate.replace(',', '')
            if not shares_no_comma.isdigit():
                continue

            # Check if valid comma grouping (after first 1-3 digits, groups of 3)
            parts = shares_candidate.split(',')
            if len(parts) > 1:
                # First part: 1-3 digits
                if not (1 <= len(parts[0]) <= 3):
                    continue
                # Other parts: exactly 3 digits each
                if not all(len(p) == 3 for p in parts[1:]):
                    continue

            # Found a valid candidate
            status = "✅" if (shares_candidate == expected_shares and ratio_candidate == expected_ratio) else "❌"

            print(f"{status} Combined: {combined_str}")
            print(f"   Strategy: {ratio_int_digits}-digit ratio")
            print(f"   Expected → shares: {expected_shares}, ratio: {expected_ratio}")
            print(f"   Got      → shares: {shares_candidate}, ratio: {ratio_candidate}")
            print()
            found_match = True
            break

        except ValueError:
            continue

    if not found_match:
        print(f"❌ Combined: {combined_str} - No valid parse found\n")
